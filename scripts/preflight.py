#!/usr/bin/env python3
"""Check RAG prerequisites without printing secrets or contacting write RPCs."""
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

def configured(name: str) -> bool:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("REPLACE_WITH") or value.lower() in {"changeme", "your_key_here"}:
        return False
    if name == "SUPABASE_URL":
        parsed = urlparse(value)
        return parsed.scheme == "https" and bool(parsed.netloc) and parsed.netloc.endswith(".supabase.co")
    return True

required = ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
missing = [key for key in required if not configured(key)]

print("Institutional RAG preflight")
for key in required:
    print(f"{key}: {'set' if configured(key) else 'missing or placeholder'}")
print(f"DROPBOX_ACCESS_TOKEN: {'set' if configured('DROPBOX_ACCESS_TOKEN') else 'not set (optional)'}")
pdf_dir = Path(os.getenv("PDF_DIR", "data/pdfs"))
pdfs = list(pdf_dir.glob("**/*.pdf")) if pdf_dir.exists() else []
print(f"PDF directory: {pdf_dir} ({len(pdfs)} PDF file(s))")

if missing:
    print("STATUS: BLOCKED — configure real values as Codespaces Secrets; placeholder values are not accepted.")
    sys.exit(2)
if not pdfs and not configured("DROPBOX_ACCESS_TOKEN"):
    print("STATUS: CONFIGURED, BUT NO SOURCE PDFs FOUND.")
    sys.exit(1)
print("STATUS: PREREQUISITES PRESENT. Run read-only list/dry-run next; database access and ingestion are not yet proven.")
