#!/usr/bin/env python3
"""Validate required secrets and test read-only Supabase/Dropbox connectivity.

This is a safe pilot gate, not a production readiness declaration. The goal is to
confirm that the environment is structurally valid and can reach required external
services without printing or exposing secrets before any live ingestion, migration,
or deployment is attempted.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from scripts.supabase_http import build_supabase_headers

load_dotenv()

DROPBOX_PILOT_PATH = "/Lesson 4 How emotions can affect your trading results.pdf"


def configured(name: str) -> bool:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("REPLACE_WITH") or value.lower() in {"changeme", "your_key_here"}:
        return False
    if name == "SUPABASE_URL":
        parsed = urlparse(value)
        return parsed.scheme == "https" and bool(parsed.netloc) and parsed.netloc.endswith(".supabase.co")
    return True


def check_supabase() -> tuple[bool, str]:
    base_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    try:
        response = requests.post(
            f"{base_url}/rest/v1/rpc/rag_worker_list_documents_page",
            headers=build_supabase_headers(key),
            json={"p_limit": 1, "p_offset": 0, "p_status": "all"},
            timeout=20,
        )
        if not response.ok:
            return False, f"HTTP {response.status_code} from the read-only worker RPC"
        data = response.json()
        if not isinstance(data, list):
            return False, "RPC response shape is not a row list"
        return True, f"read-only worker RPC reachable (sample rows: {len(data)})"
    except Exception as exc:
        return False, f"{type(exc).__name__}; check URL, secret, network and RPC exposure"


def dropbox_configured() -> bool:
    return configured("DROPBOX_ACCESS_TOKEN") or configured("DROPBOX_REFRESH_TOKEN")


def check_dropbox() -> tuple[bool,str]:
    from im19.knowledge_mining.dropbox_discovery import DropboxClient
    from im19.secrets import LegacyEnvironmentSecrets
    from im19.contracts import PipelineError
    if not dropbox_configured():
        return True,"not configured (optional for local PDF pilot)"
    try:
        client=DropboxClient(LegacyEnvironmentSecrets(),legacy_token=os.getenv("DROPBOX_ACCESS_TOKEN", ""))
        metadata=client.metadata(os.getenv("DROPBOX_PREFLIGHT_PATH",DROPBOX_PILOT_PATH))
        if metadata.get(".tag") != "file":
            return False,"Selected Dropbox source is not a file"
        return True,"read-only metadata verified; no PDF downloaded"
    except PipelineError as exc:
        return False,f"{exc.status}: {exc.code}"
    except Exception as exc:
        return False,type(exc).__name__


def main() -> int:
    required = ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
    missing = [name for name in required if not configured(name)]
    print("Institutional RAG pilot gate (read-only; safe pilot only)")
    print("This is not a production readiness declaration.")
    for name in required:
        print(f"{name}: {'set' if configured(name) else 'missing or placeholder'}")
    print(f"DROPBOX_ACCESS_TOKEN: {'set' if configured('DROPBOX_ACCESS_TOKEN') else 'not set (optional)'}")
    pdf_dir = Path(os.getenv("PDF_DIR", "data/pdfs"))
    local_pdfs = list(pdf_dir.glob("**/*.pdf")) if pdf_dir.exists() else []
    print(f"PDF directory: {pdf_dir} ({len(local_pdfs)} PDF file(s))")

    if missing:
        print("STATUS: BLOCKED — add real values as Codespaces Secrets or a local .env file, then restart the environment.")
        print("NEXT: do not attempt ingestion, migration, or deployment until the required secrets are valid and reviewed.")
        return 2

    supabase_ok, supabase_detail = check_supabase()
    print(f"Supabase connectivity: {'OK' if supabase_ok else 'FAILED'} — {supabase_detail}")
    if not supabase_ok:
        print("STATUS: BLOCKED — do not run ingestion until the database RPC check passes.")
        return 3

    dropbox_ok, dropbox_detail = check_dropbox()
    if dropbox_configured():
        print(f"Dropbox connectivity: {'OK' if dropbox_ok else 'FAILED'} — {dropbox_detail}")
    else:
        print(f"Dropbox connectivity: {dropbox_detail}")
    if not dropbox_ok and not local_pdfs:
        print("STATUS: BLOCKED — correct Dropbox token scope and path before any live PDF pilot.")
        return 4

    if not local_pdfs and not dropbox_configured():
        print("STATUS: BLOCKED — database reachable, but no source PDFs are configured. Add a local PDF or Dropbox access before a pilot.")
        return 1

    if not dropbox_ok and local_pdfs:
        print("Dropbox connector: AUTH_BLOCKED/FAILED; local PDF pilot remains available")
    print("STATUS: SAFE PILOT READY")
    print("Human approval is still required before any live ingestion, migration, bulk indexing, or production deployment.")
    print("Production readiness is not declared by this check alone; it requires retrieval evaluation, citation validation, and operational review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
