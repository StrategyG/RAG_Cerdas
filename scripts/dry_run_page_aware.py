#!/usr/bin/env python3
"""Read-only, page-aware PDF dry-run. Never connects to Supabase or Dropbox."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rag_pipeline import MODEL_DIMS, MODEL_ID, extract_page_chunks


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_report(pdf_path: Path, source_path: str, source_id: str | None,
                 tokenizer: Any) -> dict[str, Any]:
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    data = pdf_path.read_bytes()
    if not data.startswith(b"%PDF-"):
        raise ValueError("Input does not have a PDF signature")
    digest = sha256_bytes(data)
    page_count, chunks, stats = extract_page_chunks(data, tokenizer)
    page_counts = Counter(int(chunk["page_start"]) for chunk in chunks)
    problems: list[str] = []
    chunk_provenance: list[dict[str, Any]] = []
    for chunk in chunks:
        start, end = chunk.get("page_start"), chunk.get("page_end")
        if not isinstance(start, int) or not isinstance(end, int) or not (1 <= start <= end <= page_count):
            problems.append(f"invalid_page_range:{chunk.get('chunk_index')}")
        if start != end:
            problems.append(f"cross_page_chunk:{chunk.get('chunk_index')}")
        if not str(chunk.get("text_content") or "").strip():
            problems.append(f"empty_chunk:{chunk.get('chunk_index')}")
        if not chunk.get("content_sha256") or not chunk.get("metadata", {}).get("page_text_sha256"):
            problems.append(f"missing_provenance:{chunk.get('chunk_index')}")
        chunk_provenance.append({
            "chunk_index": chunk["chunk_index"],
            "chunk_id": hashlib.sha256(
                f"{digest}:{chunk['page_start']}:{chunk['chunk_index']}:{chunk['content_sha256']}".encode("utf-8")
            ).hexdigest(),
            "content_sha256": chunk["content_sha256"],
            "page_start": start,
            "page_end": end,
            "token_count": chunk["token_count"],
            "metadata": chunk["metadata"],
        })
    try:
        import sentence_transformers  # noqa: F401
        embedding_library = "available"
    except ImportError:
        embedding_library = "missing"
    return {
        "schema_version": "page-aware-dry-run-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "local_read_only_dry_run",
        "source": {
            "source_name": pdf_path.name,
            "source_path": source_path,
            "source_id": source_id,
            "local_path": str(pdf_path.resolve()),
            "bytes_read": len(data),
            "pdf_sha256": digest,
        },
        "pdf": {
            **stats,
            "page_count": page_count,
            "pages_extracted": stats["pages_with_text"],
            "chunk_count": len(chunks),
            "chunks_per_page": {str(k): page_counts[k] for k in sorted(page_counts)},
            "empty_chunks": sum(1 for c in chunks if not str(c.get("text_content") or "").strip()),
        },
        "embedding_preparation": {
            "model_id": MODEL_ID,
            "expected_dimensions": MODEL_DIMS,
            "sentence_transformers_installed": embedding_library == "available",
            "vectors_created": False,
            "status": "configuration_checked_only" if embedding_library == "available" else "blocked_missing_dependency",
        },
        "chunks": chunk_provenance,
        "validation": {
            "problems": problems,
            "page_mappings_valid": not any(p.startswith(("invalid_page_range:", "cross_page_chunk:")) for p in problems),
            "provenance_valid": not any(p.startswith("missing_provenance:") for p in problems),
            "passed": not problems and bool(chunks),
        },
        "side_effects": {
            "supabase_reads": False,
            "supabase_writes": False,
            "rpc_calls": False,
            "dropbox_reads": False,
            "dropbox_writes": False,
            "generation_activated": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, help="Path to an already-authorized local PDF")
    parser.add_argument("--source-path", default="", help="Canonical source path for provenance only")
    parser.add_argument("--source-id", default=None, help="Optional source identifier for provenance only")
    parser.add_argument("--out", default="page_aware_dry_run.json", help="JSON report output path")
    args = parser.parse_args()
    try:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
        report = build_report(Path(args.pdf), args.source_path, args.source_id, tokenizer)
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": "PASS" if report["validation"]["passed"] else "FAIL",
            "report": str(Path(args.out).resolve()),
            "pdf_sha256": report["source"]["pdf_sha256"],
            "page_count": report["pdf"]["page_count"],
            "pages_extracted": report["pdf"]["pages_extracted"],
            "chunk_count": report["pdf"]["chunk_count"],
            "validation": report["validation"],
            "embedding_preparation": report["embedding_preparation"],
            "side_effects": report["side_effects"],
        }, ensure_ascii=False, indent=2))
        return 0 if report["validation"]["passed"] else 2
    except Exception as exc:
        print(json.dumps({
            "status": "BLOCKED_OR_FAILED",
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "database_writes": False,
            "dropbox_changes": False,
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
