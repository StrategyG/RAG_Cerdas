#!/usr/bin/env python3
"""Check RAG prerequisites without printing secrets or contacting write RPCs."""
import os, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
required = ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
missing = [key for key in required if not os.getenv(key)]
print("Institutional RAG preflight")
for key in required:
    print(f"{key}: {'set' if os.getenv(key) else 'missing'}")
print(f"DROPBOX_ACCESS_TOKEN: {'set' if os.getenv('DROPBOX_ACCESS_TOKEN') else 'not set (optional)'}")
pdf_dir = Path(os.getenv("PDF_DIR", "data/pdfs"))
pdfs = list(pdf_dir.glob("**/*.pdf")) if pdf_dir.exists() else []
print(f"PDF directory: {pdf_dir} ({len(pdfs)} PDF file(s))")
if missing:
    print("STATUS: BLOCKED — configure required values as Codespaces Secrets and restart.")
    sys.exit(2)
if not pdfs and not os.getenv("DROPBOX_ACCESS_TOKEN"):
    print("STATUS: CONFIGURED, BUT NO SOURCE PDFs FOUND.")
    sys.exit(1)
print("STATUS: PREREQUISITES PRESENT. Database access and ingestion are not yet proven.")
