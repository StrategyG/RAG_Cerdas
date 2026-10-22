from pathlib import Path

import pytest

from rag_pipeline import PDFSource


def test_local_path_rejects_parent_directory_traversal(tmp_path):
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    outside_pdf = tmp_path / "outside.pdf"
    outside_pdf.write_bytes(b"%PDF-1.7 outside")

    source = PDFSource(pdf_dir)
    result = source.local_path({
        "source_path": "../outside.pdf",
        "source_name": "outside.pdf",
    })

    assert result is None


def test_local_path_rejects_symlink_resolving_outside_pdf_dir(tmp_path):
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    outside_pdf = tmp_path / "outside.pdf"
    outside_pdf.write_bytes(b"%PDF-1.7 outside")
    link = pdf_dir / "linked.pdf"

    try:
        link.symlink_to(outside_pdf)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable on this platform: {exc}")

    source = PDFSource(pdf_dir)
    result = source.local_path({
        "source_path": "/linked.pdf",
        "source_name": "linked.pdf",
    })

    assert result is None
