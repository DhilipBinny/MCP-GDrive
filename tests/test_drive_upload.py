"""Upload path shape for large local files. No network and no real file upload."""

from __future__ import annotations

from unittest import mock

from googleapiclient.http import DEFAULT_CHUNK_SIZE, DEFAULT_HTTP_TIMEOUT_SEC, build_http

from shared.drive_service import upload_file

_ALIGNED = 256 * 1024


def test_upload_is_resumable_and_streams_slices(tmp_path):
    payload = b"0123456789abcdef" * 1024
    path = tmp_path / "film.mp4"
    path.write_bytes(payload)
    captured: dict = {}

    def create(**kwargs):
        captured.update(kwargs)
        request = mock.Mock()
        request.execute.return_value = {
            "id": "file-id",
            "name": "film.mp4",
            "mimeType": "video/mp4",
            "webViewLink": "https://example.invalid/file",
        }
        return request

    service = mock.Mock()
    service.files.return_value.create.side_effect = create
    with mock.patch("shared.drive_service._get_service", return_value=service):
        result = upload_file(str(path), name="film.mp4")

    media = captured["media_body"]
    assert media.resumable() is True
    assert media.chunksize() == DEFAULT_CHUNK_SIZE
    assert DEFAULT_CHUNK_SIZE % _ALIGNED == 0
    assert media.size() == len(payload)
    assert media.getbytes(0, 4) == payload[:4]
    assert media.getbytes(100, 8) == payload[100:108]
    assert result["id"] == "file-id"
    assert captured["body"]["name"] == "film.mp4"
    # The Drive client build path uses this timeout for every HTTP request,
    # including each resumable chunk. upload_file does not override it.
    assert build_http().timeout == DEFAULT_HTTP_TIMEOUT_SEC
    assert DEFAULT_HTTP_TIMEOUT_SEC == 60
