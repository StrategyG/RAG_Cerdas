#!/usr/bin/env python3
"""Repository production gate for Institutional RAG.

This is a safe, read-only validation layer that checks the project is structurally
and operationally ready for a controlled pilot before any live ingestion, migration,
or deployment is attempted.

Modes:
- local: validates repo structure and environment placeholders without external calls.
- preflight: runs the read-only external connectivity checks for Supabase and Dropbox.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

REQUIRED_FILES = [
    "rag_pipeline.py",
    "eval_retrieval.py",
    "eval_cases.json",
    "requirements.txt",
    "requirements-test.txt",
    "scripts/preflight.py",
    "scripts/supabase_http.py",
    "scripts/download_dropbox_pdf_readonly.py",
    "supabase/migrations/20261018182702_claim_ingest_jobs_only.sql",
    "supabase/migrations/20261018183310_drop_duplicate_ingest_job_index.sql",
    "supabase/verification/verify_ingestion_state.sql",
    "supabase/verification/diagnose_ingestion_stalls.sql",
    "tests/test_page_chunking.py",
    "tests/test_eval_metrics.py",
    "tests/test_preflight.py",
    "tests/test_supabase_http.py",
    "tests/test_pipeline_dry_run.py",
    "tests/test_dropbox_readonly_download.py",
]

REQUIRED_ENV = {
    "SUPABASE_URL": "https://<project-ref>.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "non-placeholder secret",
}


def configured(name: str) -> bool:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("REPLACE_WITH"):
        return False
    if value.lower() in {"changeme", "your_key_here", "example", "placeholder"}:
        return False
    if name == "SUPABASE_URL":
        parsed = urlparse(value)
        return parsed.scheme == "https" and bool(parsed.netloc) and parsed.netloc.endswith(".supabase.co")
    return True


def local_issues() -> list[str]:
    issues: list[str] = []
    repo_root = Path(__file__).resolve().parents[1]
    for rel in REQUIRED_FILES:
        path = repo_root / rel
        if not path.is_file():
            issues.append(f"missing required file: {rel}")
    for name, hint in REQUIRED_ENV.items():
        if not configured(name):
            issues.append(f"{name} is missing or placeholder; expected {hint}")
    pdf_dir = Path(os.getenv("PDF_DIR", "data/pdfs"))
    if not pdf_dir.exists() and not os.getenv("DROPBOX_ACCESS_TOKEN"):
        issues.append("PDF_DIR has no local PDFs and DROPBOX_ACCESS_TOKEN is not set")
    return issues


def validate_local_gate() -> tuple[bool, list[str]]:
    issues = local_issues()
    return not issues, issues


def check_supabase() -> tuple[bool, str]:
    try:
        import requests
        from scripts.supabase_http import build_supabase_headers

        base_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        response = requests.post(
            f"{base_url}/rest/v1/rpc/rag_worker_list_documents_page",
            headers=build_supabase_headers(key),
            json={"p_limit": 1, "p_offset": 0, "p_status": "all"},
            timeout=20,
        )
        if not response.ok:
            return False, f"HTTP {response.status_code} from read-only worker RPC"
        data = response.json()
        if not isinstance(data, list):
            return False, "RPC response shape is not a row list"
        return True, f"read-only worker RPC reachable (sample rows: {len(data)})"
    except Exception as exc:  # pragma: no cover - environmental failure
        return False, f"{type(exc).__name__}; check URL, secret, network, and RPC exposure"


def check_dropbox() -> tuple[bool, str]:
    token = os.getenv("DROPBOX_ACCESS_TOKEN", "").strip()
    if not token:
        return True, "not configured (optional; local PDFs must be supplied)"
    try:
        import requests

        path = os.getenv("DROPBOX_PREFLIGHT_PATH", "/Lesson 4 How emotions can affect your trading results.pdf").strip()
        response = requests.post(
            "https://content.dropboxapi.com/2/files/download",
            headers={
                "Authorization": f"Bearer {token}",
                "Dropbox-API-Arg": json.dumps({"path": path}, separators=(",", ":")),
            },
            timeout=45,
        )
        if not response.ok:
            return False, f"HTTP {response.status_code} when downloading the preflight PDF"
        if not response.content.startswith(b"%PDF-"):
            return False, "Dropbox returned data without a PDF signature"
        return True, f"read-only PDF download verified ({len(response.content)} bytes)"
    except Exception as exc:  # pragma: no cover - environmental failure
        return False, f"{type(exc).__name__}; check Dropbox access and network"


def run_preflight() -> int:
    issues = local_issues()
    if issues:
        print("STATUS: LOCAL GATE FAILED")
        for issue in issues:
            print(f" - {issue}")
        return 2
    supabase_ok, supabase_detail = check_supabase()
    dropbox_ok, dropbox_detail = check_dropbox()
    print("Production gate: local checks passed.")
    print(f"Supabase connectivity: {'OK' if supabase_ok else 'FAILED'} — {supabase_detail}")
    print(f"Dropbox connectivity: {'OK' if dropbox_ok else 'FAILED'} — {dropbox_detail}")
    if not supabase_ok:
        print("STATUS: BLOCKED — fix Supabase connectivity before attempting a live pilot.")
        return 3
    if not dropbox_ok and os.getenv("DROPBOX_ACCESS_TOKEN"):
        print("STATUS: BLOCKED — fix Dropbox access before attempting a live PDF pilot.")
        return 4
    print("STATUS: READY FOR SAFE PILOT — schema and connectivity checks passed, but production launch still requires human approval.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["local", "preflight"], default="local")
    args = parser.parse_args()

    if args.mode == "local":
        ok, issues = validate_local_gate()
        if ok:
            print("STATUS: LOCAL GATE PASSED")
            print("Structure and environment placeholders look valid for a controlled pilot.")
            return 0
        print("STATUS: LOCAL GATE FAILED")
        for issue in issues:
            print(f" - {issue}")
        return 2

    return run_preflight()


if __name__ == "__main__":
    raise SystemExit(main())
