"""Bounded PDF/EPUB parser; preserves exact locators and flags incomplete extraction."""

from __future__ import annotations

from dataclasses import asdict
from io import BytesIO
import multiprocessing as mp
import posixpath
from pathlib import PurePosixPath
import re
import statistics
import zipfile

import fitz
from defusedxml import ElementTree as ET

from im19.contracts import Chunk, Page, PipelineError, digest, stable_id

MAX_BYTES = 64 * 1024 * 1024
MAX_PAGES = 2000
MAX_TEXT = 8_000_000


def needs_ocr(page, text: str) -> bool:
    area = max(1, page.rect.width * page.rect.height)
    large_image = any(
        (r.width * r.height) / area >= 0.25
        for info in page.get_images(full=True)
        for r in page.get_image_rects(info[0])
    )
    return large_image and len(text.strip()) < 80


class TesseractOCR:
    def __init__(self, language="eng", min_confidence=60):
        self.language, self.min_confidence = language, min_confidence

    def __call__(self, page):
        import pytesseract
        from PIL import Image

        # Bound decompression/render cost before rasterizing an untrusted page.
        scale = 2
        if page.rect.width * page.rect.height * scale**2 > 20_000_000:
            raise PipelineError("NEEDS_HUMAN_REVIEW", "OCR_PIXEL_QUOTA")
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        img = Image.open(BytesIO(pix.tobytes("png")))
        try:
            data = pytesseract.image_to_data(
                img, lang=self.language, output_type=pytesseract.Output.DICT, timeout=45
            )
        except RuntimeError:
            raise PipelineError("OCR_REQUIRED", "OCR_FAILED_OR_TIMEOUT") from None
        words, scores = [], []
        for text, confidence in zip(data["text"], data["conf"], strict=True):
            if text.strip() and float(confidence) >= 0:
                words.append(text)
                scores.append(float(confidence))
        confidence = sum(scores) / len(scores) if scores else 0.0
        warnings = [] if confidence >= self.min_confidence else ["LOW_OCR_CONFIDENCE"]
        return " ".join(words), confidence, warnings


def parse_pdf(data: bytes, ocr=None) -> list[Page]:
    if not data.startswith(b"%PDF-") or len(data) > MAX_BYTES:
        raise PipelineError("QUARANTINED", "INVALID_PDF_OR_SIZE")
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        raise PipelineError("QUARANTINED", "CORRUPT_PDF") from None
    pages, total = [], 0
    with doc:
        if doc.needs_pass:
            raise PipelineError("NEEDS_HUMAN_REVIEW", "PDF_ENCRYPTED")
        if not 1 <= doc.page_count <= MAX_PAGES:
            raise PipelineError("NEEDS_HUMAN_REVIEW", "PAGE_QUOTA")
        toc = doc.get_toc()
        for i, page in enumerate(doc, 1):
            text = page.get_text("text", sort=True).strip()
            blocks, confidence, used, warnings = [], None, False, []
            if needs_ocr(page, text):
                if ocr is None:
                    raise PipelineError("OCR_REQUIRED", "IMAGE_PAGE_REQUIRES_OCR")
                text, confidence, warnings = ocr(page)
                used = True
                blocks.append(
                    {"type": "ocr_paragraph", "text": text, "confidence": confidence}
                )
            else:
                layout = page.get_text(
                    "dict",
                    flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES,
                    sort=True,
                )
                sizes = [
                    s["size"]
                    for b in layout["blocks"]
                    if b["type"] == 0
                    for l in b["lines"]
                    for s in l["spans"]
                ]
                body_size = statistics.median(sizes) if sizes else 12
                for block in layout["blocks"]:
                    if block["type"] != 0:
                        continue
                    lines = [
                        "".join(s["text"] for s in line["spans"])
                        for line in block["lines"]
                    ]
                    value = "\n".join(lines).strip()
                    max_size = max(
                        (s["size"] for l in block["lines"] for s in l["spans"]),
                        default=body_size,
                    )
                    kind = (
                        "heading_candidate"
                        if max_size > body_size * 1.2
                        else "paragraph"
                    )
                    blocks.append(
                        {"type": kind, "text": value, "bbox": list(block["bbox"])}
                    )
                try:
                    for table in page.find_tables().tables:
                        blocks.append(
                            {
                                "type": "table",
                                "rows": table.extract(),
                                "bbox": list(table.bbox),
                            }
                        )
                except Exception:
                    warnings.append("TABLE_EXTRACTION_INCOMPLETE")
            hierarchy = [row for row in toc if row[2] <= i]
            if hierarchy:
                blocks.insert(0, {"type": "toc_context", "entries": hierarchy[-8:]})
            if not text:
                warnings.append("EMPTY_PAGE")
            total += len(text)
            if total > MAX_TEXT:
                raise PipelineError("NEEDS_HUMAN_REVIEW", "TEXT_QUOTA")
            pages.append(
                Page(f"pdf:page:{i}", text, i, blocks, confidence, used, warnings)
            )
    return pages


def _zip_path(name):
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or ":" in name
        or any(ord(c) < 32 for c in name)
    ):
        raise PipelineError("QUARANTINED", "EPUB_UNSAFE_MEMBER")
    return name


def parse_epub(data: bytes) -> list[Page]:
    if len(data) > MAX_BYTES:
        raise PipelineError("NEEDS_HUMAN_REVIEW", "EPUB_SIZE_QUOTA")
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            if len(names) != len(set(names)) or len(infos) > 5000:
                raise ValueError("Ambiguous archive")
            if sum(i.file_size for i in infos) > MAX_BYTES or any(
                i.file_size > 8_000_000 for i in infos
            ):
                raise PipelineError("QUARANTINED", "EPUB_EXPANSION_QUOTA")
            for info in infos:
                _zip_path(info.filename)
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise PipelineError("QUARANTINED", "EPUB_SYMLINK")
            container = ET.fromstring(archive.read("META-INF/container.xml"))
            opf = next(
                x.attrib["full-path"]
                for x in container.iter()
                if x.tag.endswith("rootfile")
            )
            _zip_path(opf)
            package = ET.fromstring(archive.read(opf))
            manifest = {
                x.attrib["id"]: x.attrib["href"]
                for x in package.iter()
                if x.tag.endswith("}item")
            }
            spine = [
                x.attrib["idref"] for x in package.iter() if x.tag.endswith("}itemref")
            ]
            if not spine or len(spine) > MAX_PAGES:
                raise PipelineError("NEEDS_HUMAN_REVIEW", "EPUB_SPINE_QUOTA")
            pages, total = [], 0
            for n, item in enumerate(spine, 1):
                href = manifest[item].split("#")[0]
                # Reject escaping relative paths and remote URLs, never fetch resources.
                path = posixpath.normpath(posixpath.join(posixpath.dirname(opf), href))
                _zip_path(path)
                root = ET.fromstring(archive.read(path))
                blocks = []
                for node in root.iter():
                    tag = node.tag.rsplit("}", 1)[-1]
                    if tag in {
                        "p",
                        "h1",
                        "h2",
                        "h3",
                        "h4",
                        "blockquote",
                        "li",
                        "table",
                        "figcaption",
                    }:
                        value = re.sub(r"\s+", " ", "".join(node.itertext())).strip()
                        if value:
                            blocks.append(
                                {"type": tag, "text": value, "anchor": node.get("id")}
                            )
                text = "\n\n".join(b["text"] for b in blocks)
                warnings = [] if text else ["EPUB_IMAGE_OR_EMPTY_SPINE_REQUIRES_REVIEW"]
                total += len(text)
                if total > MAX_TEXT:
                    raise PipelineError("NEEDS_HUMAN_REVIEW", "TEXT_QUOTA")
                pages.append(
                    Page(
                        f"epub:spine:{n}:{path}", text, None, blocks, warnings=warnings
                    )
                )
            return pages
    except PipelineError:
        raise
    except Exception:
        raise PipelineError("QUARANTINED", "CORRUPT_OR_UNSAFE_EPUB") from None


def chunk_pages(
    document_id: str, pages: list[Page], max_chars=1000, overlap=100
) -> list[Chunk]:
    if not 200 <= max_chars <= 4000 or not 0 <= overlap < max_chars:
        raise ValueError("Invalid bounded character chunk configuration")
    chunks = []
    for page in pages:
        start = 0
        while start < len(page.text):
            end = min(start + max_chars, len(page.text))
            text = page.text[start:end].strip()
            if text:
                chunks.append(
                    Chunk(
                        stable_id(document_id, page.locator, str(start), digest(text)),
                        document_id,
                        page.locator,
                        text,
                        page.page_number,
                        page.page_number,
                        digest(text),
                    )
                )
            if end == len(page.text):
                break
            start = end - overlap
    if not chunks:
        raise PipelineError("QUARANTINED", "EMPTY_EXTRACTION")
    return chunks


def _parse_child(pipe, data, extension, enable_ocr, language):
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (240, 240))
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
        pages = (
            parse_pdf(data, TesseractOCR(language) if enable_ocr else None)
            if extension == ".pdf"
            else parse_epub(data)
        )
        pipe.send({"pages": [asdict(p) for p in pages]})
    except PipelineError as exc:
        pipe.send({"status": exc.status, "code": exc.code})
    except Exception:
        pipe.send({"status": "QUARANTINED", "code": "PARSER_PROCESS_FAILED"})
    finally:
        pipe.close()


def parse_isolated(
    data: bytes, extension: str, *, enable_ocr=False, language="eng", timeout=300
) -> list[Page]:
    if extension not in {".pdf", ".epub"} or len(data) > MAX_BYTES:
        raise PipelineError("QUARANTINED", "UNSUPPORTED_FORMAT_OR_SIZE")
    context = mp.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_parse_child, args=(child, data, extension, enable_ocr, language)
    )
    process.start()
    child.close()
    try:
        if not parent.poll(timeout):
            raise PipelineError("QUARANTINED", "PARSER_TIMEOUT")
        try:
            result = parent.recv()
        except EOFError:
            raise PipelineError("QUARANTINED", "PARSER_CRASH") from None
        if "pages" not in result:
            raise PipelineError(result["status"], result["code"])
        return [Page(**page) for page in result["pages"]]
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        parent.close()
