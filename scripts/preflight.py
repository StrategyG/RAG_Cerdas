#!/usr/bin/env python3
"""Validate required secrets and test read-only Supabase/Dropbox connectivity without printing secrets."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

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
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept-Profile": "public",
                "Content-Profile": "public",
            },
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


def check_dropbox() -> tuple[bool, str]:
    token = os.getenv("DROPBOX_ACCESS_TOKEN", "").strip()
    if not token:
        return True, "not configured (optional; local PDF files must be supplied)"
    path = os.getenv("DROPBOX_PREFLIGHT_PATH", DROPBOX_PILOT_PATH).strip()
    try:
        response = requests.post(
            "https://content.dropboxapi.com/2/files/download",
            headers={
                "Authorization": f"Bearer {token}",
                "Dropbox-API-Arg": __import__("json").dumps({"path": path}, separators=(",", ":")),
            },
            timeout=45,
        )
        if not response.ok:
            return False, f"HTTP {response.status_code} when downloading the preflight PDF; check token scopes and DROPBOX_PREFLIGHT_PATH"
        if not response.content.startswith(b"%PDF-"):
            return False, "Dropbox returned data without a PDF signature"
        return True, f"read-only PDF download verified ({len(response.content)} bytes)"
    except Exception as exc:
        return False, f"{type(exc).__name__}; check Dropbox access and network"


def main() -> int:
    required = ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
    missing = [name for name in required if not configured(name)]
    print("Institutional RAG preflight (no database writes)")
    for name in required:
        print(f"{name}: {'set' if configured(name) else 'missing or placeholder'}")
    print(f"DROPBOX_ACCESS_TOKEN: {'set' if configured('DROPBOX_ACCESS_TOKEN') else 'not set (optional)'}")
    pdf_dir = Path(os.getenv("PDF_DIR", "data/pdfs"))
    local_pdfs = list(pdf_dir.glob("**/*.pdf")) if pdf_dir.exists() else []
    print(f"PDF directory: {pdf_dir} ({len(local_pdfs)} PDF file(s))")

    if missing:
        print("STATUS: BLOCKED — add real values as Codespaces Secrets, then restart the Codespace.")
        return 2

    supabase_ok, supabase_detail = check_supabase()
    print(f"Supabase connectivity: {'OK' if supabase_ok else 'FAILED'} — {supabase_detail}")
    if not supabase_ok:
        print("STATUS: BLOCKED — do not run ingestion until the database RPC check passes.")
        return 3

    dropbox_ok, dropbox_detail = check_dropbox()
    if configured("DROPBOX_ACCESS_TOKEN"):
        print(f"Dropbox connectivity: {'OK' if dropbox_ok else 'FAILED'} — {dropbox_detail}")
    else:
        print(f"Dropbox connectivity: {dropbox_detail}")
    if not dropbox_ok:
        print("STATUS: BLOCKED — correct Dropbox token scope/path before ingestion.")
        return 4
    if not local_pdfs and not configured("DROPBOX_ACCESS_TOKEN"):
        print("STATUS: DATABASE OK, BUT NO SOURCE PDFs FOUND.")
        return 1

    print("STATUS: CONNECTIVITY CHECKS PASSED. Ingestion has not been run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
