from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from scripts.dry_run_page_aware import build_report


class FakeTokenizer:
    def encode(self, text, add_special_tokens=False):
        return text.split()

    def decode(self, tokens, skip_special_tokens=True):
        return " ".join(tokens)


def make_pdf(path: Path, pages: list[str]) -> Path:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()
    return path


def test_multi_page_pdf_reports_known_one_based_pages(tmp_path):
    pdf = make_pdf(tmp_path / "two-pages.pdf", [
        "alpha beta gamma delta",
        "epsilon zeta eta theta",
    ])
    report = build_report(pdf, "/allowed/two-pages.pdf", "source-1", FakeTokenizer())

    assert report["pdf"]["page_count"] == 2
    assert report["pdf"]["pages_extracted"] == 2
    assert report["pdf"]["chunk_count"] == 2
    assert {c["page_start"] for c in report["chunks"]} == {1, 2}
    assert all(c["page_start"] == c["page_end"] for c in report["chunks"])
    assert all(c["chunk_id"] and c["content_sha256"] for c in report["chunks"])
    assert report["validation"]["passed"] is True
    assert report["side_effects"]["supabase_writes"] is False
    assert report["side_effects"]["rpc_calls"] is False
    assert report["side_effects"]["dropbox_writes"] is False


def test_pdf_without_selectable_text_is_rejected(tmp_path):
    pdf = make_pdf(tmp_path / "empty.pdf", ["", ""])
    with pytest.raises(ValueError, match="No selectable text"):
        build_report(pdf, "/allowed/empty.pdf", None, FakeTokenizer())


def test_corrupt_pdf_is_rejected(tmp_path):
    pdf = tmp_path / "corrupt.pdf"
    pdf.write_bytes(b"%PDF-not-a-real-document")
    with pytest.raises(Exception):
        build_report(pdf, "/allowed/corrupt.pdf", None, FakeTokenizer())


def test_missing_pdf_is_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_report(tmp_path / "missing.pdf", "/allowed/missing.pdf", None, FakeTokenizer())


def test_chunk_metadata_and_source_checksum_are_deterministic(tmp_path):
    pdf = make_pdf(tmp_path / "source.pdf", ["one two three four"])
    first = build_report(pdf, "/allowed/source.pdf", "source-2", FakeTokenizer())
    second = build_report(pdf, "/allowed/source.pdf", "source-2", FakeTokenizer())

    assert first["source"]["pdf_sha256"] == second["source"]["pdf_sha256"]
    assert first["chunks"] == second["chunks"]
    assert first["chunks"][0]["page_start"] == 1
    assert first["chunks"][0]["page_end"] == 1
    assert first["chunks"][0]["metadata"]["pdf_page_numbering"] == "1-based"


def test_report_is_json_serializable_and_does_not_claim_embeddings(tmp_path):
    pdf = make_pdf(tmp_path / "source.pdf", ["read only check"])
    report = build_report(pdf, "/allowed/source.pdf", None, FakeTokenizer())
    encoded = json.dumps(report)
    assert '"vectors_created": false' in encoded
    assert report["embedding_preparation"]["status"] in {
        "configuration_checked_only", "blocked_missing_dependency"
    }
