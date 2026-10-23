#!/usr/bin/env python3
"""Download one explicitly named Dropbox PDF to a local pilot workspace, read-only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

DROPBOX_DOWNLOAD_URL = "https://content.dropboxapi.com/2/files/download"


def download_pdf(
    dropbox_path: str,
    output_path: Path,
    *,
    token: str | None = None,
    expected_size: int | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    """Download exactly one PDF; never writes to Dropbox or to Supabase."""
    path = str(dropbox_path or "").strip()
    access_token = (token if token is not None else os.getenv("DROPBOX_ACCESS_TOKEN", "")).strip()
    if not access_token or access_token.startswith("REPLACE_WITH") or access_token.lower() in {
        "changeme", "your_key_here"
    }:
        raise RuntimeError("DROPBOX_ACCESS_TOKEN is missing or a placeholder")
    if not path.startswith("/") or path.startswith("//") or "\x00" in path:
        raise ValueError("Dropbox path must be one absolute path beginning with a single slash")
    if not path.casefold().endswith(".pdf"):
        raise ValueError("Only one explicitly named .pdf source is allowed")
    if expected_size is not None and expected_size < 1:
        raise ValueError("expected_size must be a positive integer when supplied")

    destination = Path(output_path)
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing local file: {destination}")
    client = session if session is not None else requests.Session()
    try:
        response = client.post(
            DROPBOX_DOWNLOAD_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Dropbox-API-Arg": json.dumps({"path": path}, separators=(",", ":")),
            },
            timeout=120,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Dropbox download request failed: {type(exc).__name__}") from None
    if not response.ok:
        raise RuntimeError(f"Dropbox download failed (HTTP {response.status_code}); check token scope and path")

    data = response.content
    if not data.startswith(b"%PDF-"):
        raise ValueError("Dropbox response does not have a PDF signature")
    if expected_size is not None and len(data) != expected_size:
        raise ValueError(f"PDF size mismatch: expected {expected_size} bytes, received {len(data)} bytes")

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Exclusive creation preserves any file that may have appeared after the initial check.
        with destination.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    return {
        "status": "downloaded_for_local_dry_run",
        "dropbox_path": path,
        "local_path": str(destination),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "dropbox_writes": False,
        "supabase_writes": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dropbox-path", required=True, help="One exact absolute Dropbox PDF path")
    parser.add_argument("--out", required=True, type=Path, help="New local output path; existing files are never overwritten")
    parser.add_argument("--expected-size", type=int, default=None, help="Optional expected byte count from verified Dropbox metadata")
    args = parser.parse_args()
    try:
        report = download_pdf(args.dropbox_path, args.out, expected_size=args.expected_size)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({
            "status": "BLOCKED_OR_FAILED",
            "error_type": type(exc).__name__,
            "error": str(exc)[:300],
            "dropbox_writes": False,
            "supabase_writes": False,
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
