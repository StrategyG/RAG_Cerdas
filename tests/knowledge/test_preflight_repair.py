from scripts import preflight
import rag_pipeline
from im19.contracts import PipelineError


def test_local_pdf_pilot_survives_dropbox_auth_block(monkeypatch, tmp_path, capsys):
    (tmp_path / "pilot.pdf").write_bytes(b"%PDF-test")
    monkeypatch.setenv("PDF_DIR", str(tmp_path))
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fixture-key")
    monkeypatch.setenv("DROPBOX_ACCESS_TOKEN", "expired-fixture")
    monkeypatch.setattr(
        preflight, "check_supabase", lambda: (True, "read-only RPC reachable")
    )
    monkeypatch.setattr(preflight, "check_dropbox", lambda: (False, "AUTH_BLOCKED"))
    assert preflight.main() == 0
    output = capsys.readouterr().out
    assert (
        "local PDF pilot remains available" in output
        and "expired-fixture" not in output
    )


def test_legacy_source_401_reports_auth_blocked_not_file_notfound(
    monkeypatch, tmp_path
):
    source = rag_pipeline.PDFSource(tmp_path, "expired")

    class Client:
        def metadata(self, path):
            raise PipelineError("AUTH_BLOCKED", "DROPBOX_UNAUTHORIZED")

    source._dropbox_client = Client()
    result = source.check_source(
        {"source_path": "/book.pdf", "source_name": "book.pdf"}
    )
    assert (
        result["status"] == "AUTH_BLOCKED"
        and result["reason"] == "DROPBOX_UNAUTHORIZED"
    )


def test_dropbox_preflight_is_metadata_only(monkeypatch):
    calls = []

    class Client:
        def __init__(self, *a, **kw):
            pass

        def metadata(self, path):
            calls.append(path)
            return {".tag": "file"}

    monkeypatch.setenv("DROPBOX_ACCESS_TOKEN", "fixture")
    monkeypatch.setattr("im19.knowledge_mining.dropbox_discovery.DropboxClient", Client)
    assert preflight.check_dropbox() == (
        True,
        "read-only metadata verified; no PDF downloaded",
    )
    assert len(calls) == 1
