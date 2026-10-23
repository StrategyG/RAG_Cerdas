"""Persistent audit ledger and conservative approval policy for the RAG manager.

This module does not execute governed actions. Critical actions remain blocked
until a separate, authenticated human-approval integration is implemented.
The JSON ledger is an audit convenience, not a tamper-proof security boundary.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MAX_LEDGER_BYTES = 2_000_000

SAFE_ACTIONS = frozenset({
    "read_only_check",
    "local_test",
    "local_dry_run",
})
HUMAN_APPROVAL_ACTIONS = frozenset({
    "merge_main",
    "supabase_write",
    "supabase_migration",
    "change_rls",
    "dropbox_write",
    "dropbox_move",
    "dropbox_delete",
    "change_sharing",
    "deploy",
    "paid_api",
    "external_data_transfer",
})


def classify_action(action: str) -> str:
    """Return ALLOW, REQUIRES_HUMAN_APPROVAL, or BLOCKED."""
    if action in SAFE_ACTIONS:
        return "ALLOW"
    if action in HUMAN_APPROVAL_ACTIONS:
        return "REQUIRES_HUMAN_APPROVAL"
    return "BLOCKED"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_ledger(data: Any) -> dict:
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported or invalid manager ledger schema.")
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Manager ledger entries must be a list.")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each manager ledger entry must be an object.")
        if not isinstance(entry.get("event"), str) or not entry["event"]:
            raise ValueError("Each ledger entry requires an event.")
        if not isinstance(entry.get("timestamp_utc"), str):
            raise ValueError("Each ledger entry requires timestamp_utc.")
    return data


def load_ledger(path: Path) -> dict:
    """Load an existing ledger or return a new empty ledger."""
    path = Path(path)
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "entries": []}
    if path.stat().st_size > MAX_LEDGER_BYTES:
        raise ValueError("Manager ledger exceeds the configured size limit.")
    data = json.loads(path.read_text(encoding="utf-8"))
    return _validate_ledger(data)


def append_event(path: Path, event: str, *, details: dict | None = None) -> dict:
    """Atomically append a small, non-sensitive audit event to a JSON ledger."""
    if not isinstance(event, str) or not event.strip():
        raise ValueError("event must be a non-empty string.")
    if details is not None and not isinstance(details, dict):
        raise ValueError("details must be an object.")
    path = Path(path)
    ledger = load_ledger(path)
    entry = {
        "timestamp_utc": utc_now(),
        "event": event.strip(),
        "details": details or {},
    }
    ledger["entries"].append(entry)
    serialized = json.dumps(ledger, indent=2, ensure_ascii=False) + "\n"
    if len(serialized.encode("utf-8")) > MAX_LEDGER_BYTES:
        raise ValueError("Manager ledger would exceed the configured size limit.")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return entry


def request_action(path: Path, action: str, *, request_id: str) -> dict:
    """Record an action decision; never execute the requested action."""
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("request_id must be a non-empty string.")
    decision = classify_action(action)
    entry = append_event(
        path,
        "action_request",
        details={
            "request_id": request_id.strip(),
            "action": action,
            "decision": decision,
            "executed": False,
        },
    )
    return {"decision": decision, "executed": False, "audit_entry": entry}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--request-action", required=True)
    parser.add_argument("--request-id", required=True)
    args = parser.parse_args()
    result = request_action(
        args.ledger, args.request_action, request_id=args.request_id
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["decision"] == "ALLOW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
