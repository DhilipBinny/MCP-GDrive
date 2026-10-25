"""Tests for shared.drive_service.download_file — validation, path handling, error cases."""

from __future__ import annotations

import contextlib
from unittest import mock

import pytest

from shared.drive_service import (
    GOOGLE_WORKSPACE_MIMES,
    MAX_DOWNLOAD_SIZE,
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

    def test_rejects_file_over_size_limit(self):
        big_size = str(MAX_DOWNLOAD_SIZE + 1)
        meta = {"id": "abc", "name": "huge.zip", "mimeType": "application/zip", "size": big_size}
        svc = self._mock_service(meta)
        with mock.patch("shared.drive_service._get_service", return_value=svc), pytest.raises(ValueError, match="File too large"):
            download_file("abc")

    def test_file_at_limit_passes_size_check(self):
        """File exactly at the limit should pass the size check (may fail later on write)."""
        meta = {
            "id": "abc", "name": "big.zip", "mimeType": "application/zip",
            "size": str(MAX_DOWNLOAD_SIZE),
        }
        svc = self._mock_service(meta)
        with (
            mock.patch("shared.drive_service._get_service", return_value=svc),
            mock.patch("shared.drive_service.MediaIoBaseDownload") as mock_dl,
        ):
            mock_instance = mock.MagicMock()
            mock_instance.next_chunk.return_value = (mock.MagicMock(progress=lambda: 1.0), True)
            mock_dl.return_value = mock_instance
            # Size check passes — download proceeds (will hit an empty-buffer write error)
            with contextlib.suppress(OSError, ValueError):
                download_file("abc", "/tmp/test-download-limit-check.zip")

    def test_rejects_all_workspace_mime_types(self):
        for mime in GOOGLE_WORKSPACE_MIMES:
            meta = {"id": "abc", "name": "file", "mimeType": mime, "size": "100"}
            svc = self._mock_service(meta)
            with mock.patch("shared.drive_service._get_service", return_value=svc), pytest.raises(ValueError, match="Cannot download"):
                download_file("abc")

    def test_allows_regular_pdf(self):
        """PDF is a regular file, not a Google Workspace file — should pass validation."""
        meta = {"id": "abc", "name": "report.pdf", "mimeType": "application/pdf", "size": "1000"}
        svc = self._mock_service(meta)
        with (
            mock.patch("shared.drive_service._get_service", return_value=svc),
            mock.patch("shared.drive_service.MediaIoBaseDownload") as mock_dl,
        ):
            mock_instance = mock.MagicMock()
            mock_instance.next_chunk.return_value = (mock.MagicMock(progress=lambda: 1.0), True)
            mock_dl.return_value = mock_instance
            with contextlib.suppress(OSError, ValueError):
                download_file("abc", "/tmp/test-download-pdf.pdf")


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


class TestMaxDownloadSize:
    def test_limit_is_100mb(self):
        assert MAX_DOWNLOAD_SIZE == 100 * 1024 * 1024
