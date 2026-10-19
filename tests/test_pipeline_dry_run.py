import json
from argparse import Namespace

import pytest

import rag_pipeline


PILOT_ID = "041f30c6-5957-49c0-a29b-e3c29a4e1ab0"


class FakeClient:
    def __init__(self):
        self.rpc_calls = []

    def list_documents(self, status):
        assert status == "discovered"
        return [
            {
                "document_id": PILOT_ID,
                "source_path": "/pilot.pdf",
                "source_name": "pilot.pdf",
                "ingest_status": "discovered",
            },
            {
                "document_id": "11111111-1111-1111-1111-111111111111",
                "source_path": "/other.pdf",
                "source_name": "other.pdf",
                "ingest_status": "discovered",
            },
        ]

    def rpc(self, name, body, timeout=120):
        self.rpc_calls.append((name, body))
        raise AssertionError("dry-run must not call write or queue RPCs")


def args_for_dry_run():
    return Namespace(
        pdf_dir="data/pdfs",
        status="discovered",
        document_id=PILOT_ID,
        audit_sources=False,
        reprocess_indexed=False,
        continue_on_error=False,
        limit=1,
        dry_run=True,
        enqueue=True,
        enqueue_only=False,
        claim_batch=1,
        embed_batch_size=8,
    )


def test_dry_run_checks_only_the_selected_source_and_performs_no_writes(monkeypatch, capsys):
    fetched = []

    class FakeSource:
        def __init__(self, pdf_dir, dropbox_token):
            pass

        def local_path(self, doc):
            return "pilot.pdf"

        def check_source(self, doc):
            return {"ok": True, "source": "pilot.pdf", "bytes": 22}

        def get_bytes(self, doc):
            fetched.append(doc["document_id"])
            return b"%PDF-1.7\nfake-pdf-bytes"

    monkeypatch.setattr(rag_pipeline, "PDFSource", FakeSource)
    monkeypatch.delenv("DROPBOX_ACCESS_TOKEN", raising=False)
    client = FakeClient()

    rc = rag_pipeline.command_ingest(args_for_dry_run(), client)
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert fetched == [PILOT_ID]
    assert report["selected_document_id"] == PILOT_ID
    assert report["source_checks"][0]["source_check"] == "ok"
    assert report["writes_performed"] is False
    assert report["selected_document_id"] == PILOT_ID
    assert client.rpc_calls == []


def test_dry_run_blocks_when_source_download_fails(monkeypatch, capsys):
    class FakeSource:
        def __init__(self, pdf_dir, dropbox_token):
            pass

        def local_path(self, doc):
            return "pilot.pdf"

        def check_source(self, doc):
            return {"ok": True, "source": "pilot.pdf", "bytes": 22}

        def get_bytes(self, doc):
            raise RuntimeError("simulated Dropbox permission failure")

    monkeypatch.setattr(rag_pipeline, "PDFSource", FakeSource)
    monkeypatch.delenv("DROPBOX_ACCESS_TOKEN", raising=False)
    client = FakeClient()

    rc = rag_pipeline.command_ingest(args_for_dry_run(), client)
    report = json.loads(capsys.readouterr().out)

    assert rc == 2
    assert report["source_checks"][0]["source_check"] == "failed"
    assert report["writes_performed"] is False
    assert client.rpc_calls == []



def test_source_audit_is_read_only_and_reports_coverage(monkeypatch, capsys):
    class FakeSource:
        def __init__(self, pdf_dir, dropbox_token):
            pass

        def check_source(self, doc):
            return {"ok": doc["document_id"] == PILOT_ID, "source": doc["source_path"],
                    "reason": None if doc["document_id"] == PILOT_ID else "not_found"}

    monkeypatch.setattr(rag_pipeline, "PDFSource", FakeSource)
    args = args_for_dry_run()
    args.dry_run = False
    args.audit_sources = True
    args.limit = 0
    client = FakeClient()

    rc = rag_pipeline.command_ingest(args, client)
    report = json.loads(capsys.readouterr().out)

    assert rc == 2
    assert report["mode"] == "source_audit"
    assert report["documents_selected"] == 2
    assert report["sources_ok"] == 1
    assert report["sources_failed"] == 1
    assert report["database_writes"] is False
    assert report["pdf_downloads"] is False
    assert client.rpc_calls == []
