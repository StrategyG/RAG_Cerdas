from io import BytesIO
from uuid import uuid4
import zipfile
import pytest
import fitz
from PIL import Image, ImageDraw, ImageFont
from im19.contracts import PipelineError, strict_json
from im19.knowledge_mining.document_processor import (
    parse_pdf,
    parse_epub,
    chunk_pages,
    parse_isolated,
    TesseractOCR,
)


def pdf(text="Market structure defines a sequence of higher highs and higher lows."):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text)
    data = doc.tobytes()
    doc.close()
    return data


def scanned_pdf():
    image = Image.new("RGB", (1000, 500), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 35)
    draw.text((40, 100), "Risk management protects capital.", font=font, fill="black")
    stream = BytesIO()
    image.save(stream, format="PNG")
    doc = fitz.open()
    page = doc.new_page(width=500, height=250)
    page.insert_image(page.rect, stream=stream.getvalue())
    data = doc.tobytes()
    doc.close()
    return data


def epub(extra=None):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "META-INF/container.xml",
            '<container><rootfile full-path="OEBPS/book.opf"/></container>',
        )
        z.writestr(
            "OEBPS/book.opf",
            '<package xmlns="urn:opf"><manifest><item id="a" href="one.xhtml"/></manifest><spine><itemref idref="a"/></spine></package>',
        )
        z.writestr(
            "OEBPS/one.xhtml",
            '<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Risk</h1><p>Manage risk first.</p></body></html>',
        )
        if extra:
            z.writestr(*extra)
    return buf.getvalue()


def test_pdf_chunk_provenance_never_crosses_pages():
    pages = parse_pdf(pdf())
    chunks = chunk_pages(str(uuid4()), pages)
    assert len(pages) == 1 and chunks[0].page_start == chunks[0].page_end == 1
    assert chunks[0].text in pages[0].text and pages[0].blocks
    assert chunk_pages(chunks[0].document_id, pages) == chunks


def test_scanned_page_blocks_partial_ingestion_and_routes_to_ocr():
    with pytest.raises(PipelineError, match="OCR_REQUIRED"):
        parse_pdf(scanned_pdf())
    pages = parse_pdf(
        scanned_pdf(), lambda _: ("Unreadable partial text", 20, ["LOW_OCR_CONFIDENCE"])
    )
    assert pages[0].ocr_used and pages[0].ocr_confidence == 20
    assert pages[0].warnings == ["LOW_OCR_CONFIDENCE"]


def test_real_tesseract_confidence_on_synthetic_scan():
    import shutil

    if not shutil.which("tesseract"):
        pytest.skip("Tesseract binary unavailable")
    pages = parse_pdf(scanned_pdf(), TesseractOCR())
    assert "capital" in pages[0].text.lower() and pages[0].ocr_confidence > 60
    assert pages[0].ocr_used


def test_encrypted_pdf_has_specific_status():
    doc = fitz.open(stream=pdf(), filetype="pdf")
    data = doc.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="secret", user_pw="password"
    )
    doc.close()
    with pytest.raises(PipelineError, match="PDF_ENCRYPTED"):
        parse_pdf(data)


def test_corrupt_pdf_quarantined():
    with pytest.raises(PipelineError, match="CORRUPT_PDF"):
        parse_pdf(b"%PDF-corrupt")


def test_isolated_parser_process_success():
    pages = parse_isolated(pdf(), ".pdf")
    assert pages[0].page_number == 1


def test_epub_structural_locations_do_not_invent_pages():
    pages = parse_epub(epub())
    assert (
        pages[0].page_number is None
        and pages[0].locator == "epub:spine:1:OEBPS/one.xhtml"
    )
    assert "Manage risk first." in pages[0].text
    assert chunk_pages(str(uuid4()), pages)[0].page_start is None


def test_epub_zip_traversal_and_xml_entities_quarantined():
    with pytest.raises(PipelineError, match="EPUB_UNSAFE_MEMBER"):
        parse_epub(epub(("../escape", "bad")))
    with pytest.raises(PipelineError):
        parse_epub(b"invalid zip")


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"a":NaN}', "```json\n{}\n```"])
def test_strict_model_json_rejects_ambiguity(raw):
    with pytest.raises(ValueError):
        strict_json(raw)
