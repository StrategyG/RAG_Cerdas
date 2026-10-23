from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.download_dropbox_pdf_readonly import DROPBOX_DOWNLOAD_URL, download_pdf


PDF_BYTES = b"%PDF-1.7\nminimal test fixture"


class FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code
        self.ok = 200 <= status_code < 300


class FakeSession:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls = []

    def post(self, url, *, headers, timeout):
        self.calls.append((url, headers, timeout))
        return self.response


def test_downloads_one_pdf_and_reports_checksum_without_printing_secret(tmp_path: Path):
    session = FakeSession(FakeResponse(PDF_BYTES))
    destination = tmp_path / "pilot.pdf"

    report = download_pdf(
        "/Ikigai .pdf",
        destination,
        token="test-secret-token",
        expected_size=len(PDF_BYTES),
        session=session,
    )

    assert destination.read_bytes() == PDF_BYTES
    assert report["status"] == "downloaded_for_local_dry_run"
    assert report["bytes"] == len(PDF_BYTES)
    assert report["sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    assert report["dropbox_writes"] is False
    assert report["supabase_writes"] is False
    assert len(session.calls) == 1
    url, headers, timeout = session.calls[0]
    assert url == DROPBOX_DOWNLOAD_URL
    assert headers["Authorization"] == "Bearer test-secret-token"
    assert json.loads(headers["Dropbox-API-Arg"]) == {"path": "/Ikigai .pdf"}
    assert timeout == 120
    assert "test-secret-token" not in json.dumps(report)


def test_missing_token_blocks_before_network_or_file_write(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("DROPBOX_ACCESS_TOKEN", raising=False)
    session = FakeSession(FakeResponse(PDF_BYTES))
    destination = tmp_path / "pilot.pdf"

    with pytest.raises(RuntimeError, match="DROPBOX_ACCESS_TOKEN"):
        download_pdf("/Ikigai .pdf", destination, session=session)

    assert session.calls == []
    assert not destination.exists()


@pytest.mark.parametrize("path", ["Ikigai.pdf", "//shared/Ikigai.pdf", "/folder/book.txt", "/bad\x00path.pdf"])
def test_invalid_source_path_is_rejected(path: str, tmp_path: Path):
    session = FakeSession(FakeResponse(PDF_BYTES))
    with pytest.raises(ValueError):
        download_pdf(path, tmp_path / "pilot.pdf", token="test-token", session=session)
    assert session.calls == []


def test_existing_destination_is_never_overwritten(tmp_path: Path):
    destination = tmp_path / "pilot.pdf"
    destination.write_bytes(b"existing")
    session = FakeSession(FakeResponse(PDF_BYTES))

    with pytest.raises(FileExistsError):
        download_pdf("/Ikigai .pdf", destination, token="test-token", session=session)

    assert destination.read_bytes() == b"existing"
    assert session.calls == []


def test_non_pdf_response_is_rejected_without_creating_file(tmp_path: Path):
    destination = tmp_path / "pilot.pdf"
    session = FakeSession(FakeResponse(b"not a pdf"))

    with pytest.raises(ValueError, match="PDF signature"):
        download_pdf("/Ikigai .pdf", destination, token="test-token", session=session)

    assert not destination.exists()


def test_size_mismatch_is_rejected_without_creating_file(tmp_path: Path):
    destination = tmp_path / "pilot.pdf"
    session = FakeSession(FakeResponse(PDF_BYTES))

    with pytest.raises(ValueError, match="size mismatch"):
        download_pdf("/Ikigai .pdf", destination, token="test-token",
                     expected_size=len(PDF_BYTES) + 1, session=session)

    assert not destination.exists()


def test_http_error_does_not_include_response_body_or_token(tmp_path: Path):
    destination = tmp_path / "pilot.pdf"
    session = FakeSession(FakeResponse(b"private error body", status_code=401))

    with pytest.raises(RuntimeError) as error:
        download_pdf("/Ikigai .pdf", destination, token="test-secret-token", session=session)

    assert "private error body" not in str(error.value)
    assert "test-secret-token" not in str(error.value)
    assert not destination.exists()
