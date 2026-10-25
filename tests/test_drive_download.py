"""Tests for shared.drive_service.download_file — validation, path handling, error cases."""

from __future__ import annotations

from unittest import mock

import pytest

from shared.drive_service import (
    GOOGLE_WORKSPACE_MIMES,
    _guess_extension,
    download_file,
)


class TestDownloadFileValidation:
    """Tests that don't hit the real API — mock the Drive service."""

    def _mock_service(self, meta: dict):
        """Create a mock Drive service that returns given metadata."""
        svc = mock.MagicMock()
        get_req = mock.MagicMock()
        get_req.execute.return_value = meta
        svc.files.return_value.get.return_value = get_req
        svc.files.return_value.get_media.return_value = mock.MagicMock()
        return svc

    def test_rejects_google_docs_file(self):
        meta = {"id": "abc", "name": "My Doc", "mimeType": "application/vnd.google-apps.document", "size": "100"}
        svc = self._mock_service(meta)
        with mock.patch("shared.drive_service._get_service", return_value=svc), pytest.raises(ValueError, match="Cannot download Google Workspace file"):
            download_file("abc")

    def test_rejects_google_sheets_file(self):
        meta = {"id": "abc", "name": "My Sheet", "mimeType": "application/vnd.google-apps.spreadsheet", "size": "100"}
        svc = self._mock_service(meta)
        with mock.patch("shared.drive_service._get_service", return_value=svc), pytest.raises(ValueError, match="Cannot download Google Workspace file"):
            download_file("abc")

    def test_rejects_google_slides_file(self):
        meta = {"id": "abc", "name": "My Deck", "mimeType": "application/vnd.google-apps.presentation", "size": "100"}
        svc = self._mock_service(meta)
        with mock.patch("shared.drive_service._get_service", return_value=svc), pytest.raises(ValueError, match="Cannot download Google Workspace file"):
            download_file("abc")

    def test_rejects_missing_size_field(self):
        meta = {"id": "abc", "name": "shortcut", "mimeType": "application/vnd.google-apps.shortcut"}
        svc = self._mock_service(meta)
        with mock.patch("shared.drive_service._get_service", return_value=svc), pytest.raises(ValueError, match="Cannot determine file size"):
            download_file("abc")

    def test_rejects_all_workspace_mime_types(self):
        for mime in GOOGLE_WORKSPACE_MIMES:
            meta = {"id": "abc", "name": "file", "mimeType": mime, "size": "100"}
            svc = self._mock_service(meta)
            with mock.patch("shared.drive_service._get_service", return_value=svc), pytest.raises(ValueError, match="Cannot download"):
                download_file("abc")

    def test_streams_regular_file_to_disk(self, tmp_path):
        """PDF passes validation and streams to disk via MediaIoBaseDownload."""
        meta = {"id": "abc", "name": "report.pdf", "mimeType": "application/pdf", "size": "1000"}
        svc = self._mock_service(meta)
        out_file = tmp_path / "report.pdf"

        def fake_download(fh, request):
            fh.write(b"fake-pdf-content")
            instance = mock.MagicMock()
            instance.next_chunk.return_value = (mock.MagicMock(), True)
            return instance

        with (
            mock.patch("shared.drive_service._get_service", return_value=svc),
            mock.patch("shared.drive_service.MediaIoBaseDownload", side_effect=fake_download),
        ):
            result = download_file("abc", str(out_file))
            assert result["name"] == "report.pdf"
            assert result["mime_type"] == "application/pdf"
            assert out_file.exists()
            assert out_file.read_bytes() == b"fake-pdf-content"
            assert result["size"] == 16

    def test_md5_match_on_correct_download(self, tmp_path):
        """MD5 verification passes when checksum matches."""
        import hashlib
        content = b"hello-world-content"
        expected_md5 = hashlib.md5(content).hexdigest()
        meta = {
            "id": "abc", "name": "data.bin", "mimeType": "application/octet-stream",
            "size": str(len(content)), "md5Checksum": expected_md5,
        }
        svc = self._mock_service(meta)
        out_file = tmp_path / "data.bin"

        def fake_download(fh, request):
            fh.write(content)
            instance = mock.MagicMock()
            instance.next_chunk.return_value = (mock.MagicMock(), True)
            return instance

        with (
            mock.patch("shared.drive_service._get_service", return_value=svc),
            mock.patch("shared.drive_service.MediaIoBaseDownload", side_effect=fake_download),
        ):
            result = download_file("abc", str(out_file))
            assert result["md5_match"] is True
            assert "expected_md5" not in result

    def test_md5_mismatch_detected(self, tmp_path):
        """MD5 verification reports mismatch when content differs from metadata checksum."""
        meta = {
            "id": "abc", "name": "data.bin", "mimeType": "application/octet-stream",
            "size": "10", "md5Checksum": "0000000000000000deadbeef00000000",
        }
        svc = self._mock_service(meta)
        out_file = tmp_path / "data.bin"

        def fake_download(fh, request):
            fh.write(b"wrong-data")
            instance = mock.MagicMock()
            instance.next_chunk.return_value = (mock.MagicMock(), True)
            return instance

        with (
            mock.patch("shared.drive_service._get_service", return_value=svc),
            mock.patch("shared.drive_service.MediaIoBaseDownload", side_effect=fake_download),
        ):
            result = download_file("abc", str(out_file))
            assert result["md5_match"] is False
            assert result["expected_md5"] == "0000000000000000deadbeef00000000"
            assert "actual_md5" in result

    def test_auto_names_from_drive_metadata(self, tmp_path):
        """When no output_path, filename comes from Drive metadata."""
        meta = {"id": "abc", "name": "photo.png", "mimeType": "image/png", "size": "500"}
        svc = self._mock_service(meta)

        def fake_download(fh, request):
            fh.write(b"PNG")
            instance = mock.MagicMock()
            instance.next_chunk.return_value = (mock.MagicMock(), True)
            return instance

        import os
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            with (
                mock.patch("shared.drive_service._get_service", return_value=svc),
                mock.patch("shared.drive_service.MediaIoBaseDownload", side_effect=fake_download),
            ):
                result = download_file("abc")
                assert "photo.png" in result["path"]
        finally:
            os.chdir(original_cwd)


class TestGoogleWorkspaceMimes:
    def test_all_workspace_mimes_have_correct_prefix(self):
        for mime in GOOGLE_WORKSPACE_MIMES:
            assert mime.startswith("application/vnd.google-apps.")

    def test_regular_mimes_not_blocked(self):
        assert "image/png" not in GOOGLE_WORKSPACE_MIMES
        assert "application/pdf" not in GOOGLE_WORKSPACE_MIMES
        assert "video/mp4" not in GOOGLE_WORKSPACE_MIMES
        assert "audio/mpeg" not in GOOGLE_WORKSPACE_MIMES


class TestGuessExtension:
    def test_png(self):
        assert _guess_extension("image/png") == ".png"

    def test_pdf(self):
        assert _guess_extension("application/pdf") == ".pdf"

    def test_mp4(self):
        ext = _guess_extension("video/mp4")
        assert ext in (".mp4", ".m4v")

    def test_unknown_returns_empty(self):
        assert _guess_extension("application/x-totally-unknown-format-xyz") == ""

    def test_jpeg(self):
        ext = _guess_extension("image/jpeg")
        assert ext in (".jpg", ".jpeg", ".jpe")
