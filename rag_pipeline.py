#!/usr/bin/env python3
"""Page-aware PDF ingestion + multilingual 384D embeddings for Institutional RAG.

Database writes go only through service-role-only RPCs. Never commit credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import fitz  # PyMuPDF
import requests
from dotenv import load_dotenv
from scripts.supabase_http import build_supabase_headers

MODEL_ID = "intfloat/multilingual-e5-small"
MODEL_DIMS = 384
CHUNK_TOKENS = 350
CHUNK_OVERLAP = 40
DEFAULT_EMBED_BATCH = 24

load_dotenv()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_page_text(value: str) -> str:
    value = value.replace("\u00ad", "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[\t\u00a0 ]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def extract_page_chunks(pdf_bytes: bytes, tokenizer: Any, max_tokens: int = CHUNK_TOKENS,
                        overlap: int = CHUNK_OVERLAP) -> tuple[int, list[dict[str, Any]], dict[str, Any]]:
    """Extract pages, then split *within each page* so citations never cross pages."""
    if max_tokens < 64 or overlap < 0 or overlap >= max_tokens:
        raise ValueError("Require max_tokens >= 64 and 0 <= overlap < max_tokens")

    chunks: list[dict[str, Any]] = []
    page_text_digests: dict[str, str] = {}
    total_nonempty_pages = 0
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_count = int(document.page_count)
        if page_count < 1:
            raise ValueError("PDF has no pages")
        chunk_index = 0
        for page_no, page in enumerate(document, start=1):
            page_text = normalize_page_text(page.get_text("text", sort=True))
            if not page_text:
                continue
            total_nonempty_pages += 1
            page_text_digests[str(page_no)] = sha256_text(page_text)
            ids = tokenizer.encode(page_text, add_special_tokens=False)
            cursor = 0
            while cursor < len(ids):
                end = min(cursor + max_tokens, len(ids))
                text = tokenizer.decode(ids[cursor:end], skip_special_tokens=True).strip()
                if text:
                    chunks.append({
                        "chunk_index": chunk_index,
                        "page_start": page_no,
                        "page_end": page_no,
                        "text_content": text,
                        "token_count": len(tokenizer.encode(text, add_special_tokens=False)),
                        "content_sha256": sha256_text(text),
                        "metadata": {
                            "extractor": "PyMuPDF",
                            "chunking_version": "page-aware-v1",
                            "page_text_sha256": page_text_digests[str(page_no)],
                            "token_start": cursor,
                            "token_end": end,
                            "pdf_page_numbering": "1-based",
                        },
                    })
                    chunk_index += 1
                if end >= len(ids):
                    break
                cursor = end - overlap
        if not chunks:
            raise ValueError(
                "No selectable text extracted. This PDF may be scanned/image-only; OCR is required before ingestion."
            )
        return page_count, chunks, {
            "page_count": page_count,
            "pages_with_text": total_nonempty_pages,
            "pages_without_text": page_count - total_nonempty_pages,
            "chunk_count": len(chunks),
            "page_mapping": "one_pdf_page_per_chunk",
        }
    finally:
        document.close()


class RAGClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        parsed = urlparse(self.base_url)
        if not self.base_url or not self.service_key:
            raise RuntimeError(
                "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in Codespaces Secrets or a git-ignored .env file. "
                "Never paste the key into chat or commit it."
            )
        if parsed.scheme != "https" or not parsed.netloc.endswith(".supabase.co"):
            raise RuntimeError("SUPABASE_URL must be an https://<project-ref>.supabase.co URL.")
        if self.service_key.startswith("REPLACE_WITH"):
            raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is a placeholder, not a usable secret.")
        self.http = requests.Session()
        self.headers = build_supabase_headers(self.service_key)

    def rpc(self, name: str, body: dict[str, Any], timeout: int = 120) -> Any:
        response = self.http.post(
            f"{self.base_url}/rest/v1/rpc/{name}",
            headers=self.headers,
            json=body,
            timeout=timeout,
        )
        if not response.ok:
            # Do not log headers, URLs with secrets, or request bodies.
            try:
                detail = response.json()
            except Exception:
                detail = response.text[:1000]
            raise RuntimeError(f"RPC {name} failed ({response.status_code}): {detail}")
        if not response.content:
            return None
        return response.json()

    def list_documents(self, status: str = "all", page_size: int = 200) -> list[dict[str, Any]]:
        all_rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            rows = self.rpc("rag_worker_list_documents_page", {
                "p_limit": page_size,
                "p_offset": offset,
                "p_status": status,
            })
            rows = rows or []
            all_rows.extend(rows)
            if len(rows) < page_size:
                return all_rows
            offset += len(rows)

    def get_document(self, document_id: str) -> dict[str, Any]:
        rows = self.rpc("rag_worker_get_document", {"p_document_id": document_id}) or []
        if not rows:
            raise RuntimeError(f"Document id not found: {document_id}")
        return rows[0]

    def list_chunks(self, document_id: str) -> list[dict[str, Any]]:
        rows = self.rpc("rag_worker_list_chunks", {
            "p_document_id": document_id,
            "p_only_unembedded": True,
            "p_limit": 10000,
        }) or []
        return rows


class PDFSource:
    def __init__(self, pdf_dir: Path, dropbox_token: str | None = None) -> None:
        self.pdf_dir = pdf_dir.resolve()
        self.dropbox_token = dropbox_token
        self.http = requests.Session()

    def local_path(self, document: dict[str, Any]) -> Path | None:
        source_path = str(document.get("source_path") or "").replace("\\", "/")
        cleaned = source_path.lstrip("/")
        if cleaned:
            direct = self.pdf_dir / cleaned
            if direct.is_file() and direct.suffix.lower() == ".pdf":
                return direct
        source_name = str(document.get("source_name") or "")
        if source_name:
            matches = [p for p in self.pdf_dir.rglob("*")
                       if p.is_file() and p.suffix.lower() == ".pdf"
                       and p.name.casefold() == source_name.casefold()
                       and ".dropbox_cache" not in p.parts]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                # Prefer a matching relative path if multiple basenames exist.
                path_matches = [p for p in matches if p.relative_to(self.pdf_dir).as_posix().casefold() == cleaned.casefold()]
                if len(path_matches) == 1:
                    return path_matches[0]
        return None

    def check_source(self, document: dict[str, Any]) -> dict[str, Any]:
        """Check source existence/type/size without downloading a Dropbox PDF."""
        local = self.local_path(document)
        expected_size = int(document.get("file_size_bytes") or 0)
        if local is not None:
            try:
                size = local.stat().st_size
                with local.open("rb") as handle:
                    signature = handle.read(5)
                if signature != b"%PDF-":
                    return {"ok": False, "source": str(local), "reason": "invalid_pdf_signature"}
                if expected_size and size != expected_size:
                    return {"ok": False, "source": str(local), "reason": "size_mismatch",
                            "expected_bytes": expected_size, "actual_bytes": size}
                return {"ok": True, "source": str(local), "bytes": size}
            except OSError as exc:
                return {"ok": False, "source": str(local), "reason": type(exc).__name__}
        if not self.dropbox_token:
            return {"ok": False, "source": str(document.get("source_path") or ""),
                    "reason": "not_local_and_dropbox_token_missing"}
        path = str(document.get("source_path") or "")
        if not path.startswith("/"):
            return {"ok": False, "source": path, "reason": "dropbox_path_not_absolute"}
        try:
            resp = self.http.post(
                "https://api.dropboxapi.com/2/files/get_metadata",
                headers={
                    "Authorization": f"Bearer {self.dropbox_token}",
                    "Content-Type": "application/json",
                },
                json={"path": path},
                timeout=45,
            )
            if not resp.ok:
                return {"ok": False, "source": path, "reason": f"dropbox_metadata_http_{resp.status_code}"}
            metadata = resp.json()
            if metadata.get(".tag") != "file":
                return {"ok": False, "source": path, "reason": "dropbox_path_is_not_a_file"}
            actual_size = int(metadata.get("size") or 0)
            if expected_size and actual_size != expected_size:
                return {"ok": False, "source": path, "reason": "size_mismatch",
                        "expected_bytes": expected_size, "actual_bytes": actual_size}
            if not str(metadata.get("name") or path).lower().endswith(".pdf"):
                return {"ok": False, "source": path, "reason": "not_a_pdf_filename"}
            return {"ok": True, "source": path, "bytes": actual_size}
        except Exception as exc:
            return {"ok": False, "source": path, "reason": type(exc).__name__}

    def get_bytes(self, document: dict[str, Any]) -> bytes:
        local = self.local_path(document)
        if local is not None:
            data = local.read_bytes()
        else:
            if not self.dropbox_token:
                raise FileNotFoundError(
                    f"PDF not found locally for {document.get('source_path')!r}; put it under PDF_DIR or configure DROPBOX_ACCESS_TOKEN."
                )
            path = str(document.get("source_path") or "")
            if not path.startswith("/"):
                raise ValueError(f"Dropbox source_path must be an absolute Dropbox path, got {path!r}")
            resp = self.http.post(
                "https://content.dropboxapi.com/2/files/download",
                headers={
                    "Authorization": f"Bearer {self.dropbox_token}",
                    "Dropbox-API-Arg": json.dumps({"path": path}, separators=(",", ":")),
                },
                timeout=180,
            )
            if not resp.ok:
                raise RuntimeError(f"Dropbox download failed for {path} ({resp.status_code})")
            data = resp.content
        if not data.startswith(b"%PDF-"):
            raise ValueError(f"Source for {document.get('source_path')} does not look like a PDF")
        expected_size = int(document.get("file_size_bytes") or 0)
        if expected_size and len(data) != expected_size:
            raise ValueError(
                f"Source size changed for {document.get('source_path')}: expected {expected_size}, got {len(data)}"
            )
        return data


def load_embedding_model():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("Install dependencies with `pip install -r requirements.txt`") from exc
    model = SentenceTransformer(MODEL_ID, device="cpu")
    model.max_seq_length = 512
    return model


def encode_passages(model: Any, texts: list[str], batch_size: int = DEFAULT_EMBED_BATCH) -> list[list[float]]:
    inputs = ["passage: " + t for t in texts]
    arr = model.encode(
        inputs,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    if arr.ndim != 2 or arr.shape[1] != MODEL_DIMS:
        raise RuntimeError(f"Model output shape must be (*, {MODEL_DIMS}); got {getattr(arr, 'shape', None)}")
    return [[round(float(x), 7) for x in row] for row in arr]


def embed_document(client: RAGClient, model: Any, document_id: str, batch_size: int) -> dict[str, int]:
    chunks = client.list_chunks(document_id)
    if not chunks:
        raise RuntimeError("No unembedded chunks were returned after page-aware extraction")
    updated = 0
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start:start + batch_size]
        vectors = encode_passages(model, [c["text_content"] for c in batch], batch_size=batch_size)
        payload = [{
            "chunk_id": c["chunk_id"],
            "content_sha256": c["content_sha256"],
            "embedding": v,
        } for c, v in zip(batch, vectors, strict=True)]
        result = client.rpc("rag_worker_store_embeddings", {
            "p_items": payload,
            "p_model": MODEL_ID,
        })
        if isinstance(result, dict):
            stored = int(result.get("stored", 0))
            updated += stored
            if stored != len(batch):
                raise RuntimeError(
                    f"Embedding batch stored {stored}/{len(batch)} rows; stale hash or page mapping mismatch."
                )
        else:
            raise RuntimeError(f"Unexpected embedding-store result: {result!r}")
    return {"chunks_seen": len(chunks), "embeddings_stored": updated}


def process_job(client: RAGClient, source: PDFSource, model: Any, job: dict[str, Any], embed_batch_size: int) -> dict[str, Any]:
    job_id = str(job["job_id"])
    document_id = str(job["document_id"])
    worker_id = str(job["worker_id"])
    try:
        if job.get("job_type") != "ingest":
            raise RuntimeError(f"Unsupported job_type {job.get('job_type')!r}; this worker handles ingest jobs only.")
        doc = client.get_document(document_id)
        pdf_bytes = source.get_bytes(doc)
        tokenizer = model.tokenizer
        page_count, chunks, extraction_stats = extract_page_chunks(pdf_bytes, tokenizer)
        client.rpc("rag_worker_replace_document_chunks", {
            "p_document_id": document_id,
            "p_page_count": page_count,
            "p_chunks": chunks,
        })
        embedding_stats = embed_document(client, model, document_id, embed_batch_size)
        result = {**extraction_stats, **embedding_stats, "document_id": document_id, "status": "indexed"}
        client.rpc("rag_worker_finish_job", {
            "p_job_id": job_id,
            "p_worker_id": worker_id,
            "p_success": True,
            "p_stats": result,
            "p_error": None,
        })
        return result
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        try:
            client.rpc("rag_worker_set_document_error", {
                "p_document_id": document_id,
                "p_error": message[:4000],
            })
        except Exception as audit_exc:
            print(f"WARN could not mark document failed: {type(audit_exc).__name__}", file=sys.stderr)
        try:
            client.rpc("rag_worker_finish_job", {
                "p_job_id": job_id,
                "p_worker_id": worker_id,
                "p_success": False,
                "p_stats": {"worker": "page-aware-v1"},
                "p_error": message[:4000],
            })
        except Exception as job_exc:
            print(f"WARN could not finish job: {type(job_exc).__name__}", file=sys.stderr)
        return {"document_id": document_id, "status": "error", "error": message[:1000]}


def command_list(client: RAGClient) -> int:
    docs = client.list_documents("all")
    counts: dict[str, int] = {}
    for doc in docs:
        status = str(doc.get("ingest_status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    print(json.dumps({"documents": len(docs), "status_counts": counts}, ensure_ascii=False, indent=2))
    return 0


def command_ingest(args: argparse.Namespace, client: RAGClient) -> int:
    pdf_dir = Path(args.pdf_dir)
    dropbox_token = os.getenv("DROPBOX_ACCESS_TOKEN") or None
    source = PDFSource(pdf_dir, dropbox_token)
    all_docs = client.list_documents(args.status)
    if args.status == "all" and not getattr(args, "reprocess_indexed", False):
        # "all" means all recoverable work, not reprocessing documents already indexed.
        all_docs = [doc for doc in all_docs if doc.get("ingest_status") not in {"indexed", "skipped"}]
    if args.document_id:
        all_docs = [doc for doc in all_docs if str(doc.get("document_id")) == args.document_id]
        if not all_docs:
            print(json.dumps({
                "mode": "blocked",
                "reason": "document_id_not_found_for_selected_status",
                "document_id": args.document_id,
                "status_filter": args.status,
                "writes_performed": False,
            }, ensure_ascii=False, indent=2), file=sys.stderr)
            return 2
    if args.limit < 0:
        raise ValueError("--limit must be >= 0 (0 means no limit)")
    candidate_count = len(all_docs)
    selected = all_docs[:args.limit] if args.limit > 0 else all_docs

    # Audit-only mode uses Dropbox metadata; it does not download PDFs or write to Supabase.
    if getattr(args, "audit_sources", False):
        checks = []
        for doc in selected:
            check = source.check_source(doc)
            checks.append({
                "document_id": doc.get("document_id"),
                "source_name": doc.get("source_name"),
                "ingest_status": doc.get("ingest_status"),
                **check,
            })
        good = sum(1 for item in checks if item["ok"])
        report = {
            "mode": "source_audit",
            "documents_selected": len(selected),
            "eligible_before_limit": candidate_count,
            "selection_limit": args.limit if args.limit > 0 else "all_recoverable",
            "sources_ok": good,
            "sources_failed": len(checks) - good,
            "results": checks,
            "database_writes": False,
            "pdf_downloads": False,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if checks and good == len(checks) else 2

    # Verify source metadata/signature and expected file size before queuing any work.
    checks = [(doc, source.check_source(doc)) for doc in selected]
    prepared = [doc for doc, check in checks if check["ok"]]
    missing = [
        {"document_id": doc.get("document_id"), "source_name": doc.get("source_name"), **check}
        for doc, check in checks if not check["ok"]
    ]
    if args.dry_run:
        source_checks: list[dict[str, Any]] = []
        source_check_failed = False
        for doc in prepared:
            try:
                data = source.get_bytes(doc)
                source_checks.append({
                    "document_id": doc["document_id"],
                    "source_name": doc.get("source_name"),
                    "source_check": "ok",
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                })
            except Exception as exc:
                source_check_failed = True
                source_checks.append({
                    "document_id": doc.get("document_id"),
                    "source_name": doc.get("source_name"),
                    "source_check": "failed",
                    "error": f"{type(exc).__name__}: {exc}"[:500],
                })
        report = {
            "mode": "dry_run",
            "documents_selected": len(selected),
            "documents_source_valid": len(prepared),
            "documents_source_failed": len(missing) + sum(1 for item in source_checks if item["source_check"] == "failed"),
            "selection_limit": args.limit if args.limit > 0 else "all_recoverable",
            "selected_document_id": args.document_id,
            "source_audit_failures": missing,
            "source_checks": source_checks,
            "model": MODEL_ID,
            "vector_dimensions": MODEL_DIMS,
            "writes_performed": False,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2 if source_check_failed or missing or not source_checks else 0
    if not prepared:
        print(json.dumps({
            "mode": "blocked",
            "reason": "no_selected_documents_have_verified_sources",
            "selected_documents": len(selected),
            "source_failures": missing[:50],
            "writes_performed": False,
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    if args.enqueue:
        ids = [str(doc["document_id"]) for doc in prepared]
        enqueued = 0
        for start in range(0, len(ids), 100):
            result = client.rpc("rag_worker_enqueue_jobs", {
                "p_document_ids": ids[start:start + 100],
                "p_job_type": "ingest",
            })
            enqueued += int(result or 0)
        print(json.dumps({
            "documents_source_valid": len(prepared),
            "jobs_newly_enqueued": enqueued,
            "source_failures_skipped": len(missing),
            "sample_source_failures": missing[:20],
        }, ensure_ascii=False))
    if args.enqueue_only:
        return 2 if missing else 0

    model = load_embedding_model()
    worker_id = f"codespaces-{os.getenv('CODESPACE_NAME', 'local')}"
    processed = 0
    errors = 0
    while True:
        claimed = client.rpc("rag_worker_claim_ingest_jobs", {
            "p_worker_id": worker_id,
            "p_limit": args.claim_batch,
            "p_document_ids": [str(doc["document_id"]) for doc in prepared],
        }) or []
        if not claimed:
            break
        for row in claimed:
            job = dict(row)
            job["worker_id"] = worker_id
            result = process_job(client, source, model, job, args.embed_batch_size)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            processed += 1
            if result["status"] == "error":
                errors += 1
                if not getattr(args, "continue_on_error", False):
                    break
        if errors and not getattr(args, "continue_on_error", False):
            break
    summary = {
        "selected_documents": len(selected),
        "source_valid_documents": len(prepared),
        "source_failed_documents": len(missing),
        "processed_jobs": processed,
        "errors": errors,
        "model": MODEL_ID,
        "continue_on_error": getattr(args, "continue_on_error", False),
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 1 if errors or missing else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="Read-only status summary")
    ingest = sub.add_parser("ingest", help="Queue available PDFs and run page-aware ingestion + embeddings")
    ingest.add_argument("--pdf-dir", default=os.getenv("PDF_DIR", "data/pdfs"))
    ingest.add_argument("--status", default="discovered", choices=["all", "discovered", "queued", "processing", "indexed", "failed", "skipped"])
    ingest.add_argument("--document-id", default=None, help="Restrict this run to one exact document UUID (recommended for pilot validation)")
    ingest.add_argument("--audit-sources", action="store_true", help="Check source metadata/signature without downloading PDFs or writing to the database")
    ingest.add_argument("--reprocess-indexed", action="store_true", help="Include indexed/skipped documents when --status all is selected")
    ingest.add_argument("--continue-on-error", action="store_true", help="Continue through the selected corpus after individual document failures")
    ingest.add_argument("--enqueue", action=argparse.BooleanOptionalAction, default=True,
                        help="Queue eligible documents before processing (default: enabled)")
    ingest.add_argument("--enqueue-only", action="store_true", help="Queue available PDFs, then exit without processing")
    ingest.add_argument("--dry-run", action="store_true", help="Inspect PDF coverage; no database writes")
    ingest.add_argument("--claim-batch", type=int, default=5)
    ingest.add_argument("--embed-batch-size", type=int, default=DEFAULT_EMBED_BATCH)
    ingest.add_argument("--limit", type=int, default=1, help="Maximum eligible documents per run; use 0 only after pilot validation to process all selected documents.")
    args = parser.parse_args()

    client = RAGClient()
    if args.command == "list":
        return command_list(client)
    if args.command == "ingest":
        return command_ingest(args, client)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
