#!/usr/bin/env python3
"""Bounded, non-destructive task runner for the Institutional RAG pilot.

This is a deterministic safety scaffold, not an LLM agent. It executes only
predefined read-only/local validation tasks. It never accesses secrets,
Supabase, Dropbox, GitHub APIs, or production data.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
MAX_TASKS_PER_RUN = 5
ALLOWED_TASKS: dict[str, tuple[str, ...]] = {
    "compile": (
        sys.executable, "-m", "py_compile",
        "rag_pipeline.py", "eval_retrieval.py", "scripts/preflight.py",
    ),
    "unit_tests": (
        sys.executable, "-m", "pytest", "-q", "--strict-config",
        "--strict-markers", "tests",
    ),
    "eval_schema": (
        sys.executable, "-c",
        "import json; from pathlib import Path; "
        "p=json.loads(Path('eval_cases.json').read_text(encoding='utf-8')); "
        "assert isinstance(p,list) and p; "
        "ids=[x.get('query_id') for x in p]; "
        "assert all(isinstance(x,str) and x for x in ids); "
        "assert len(ids)==len(set(ids)); "
        "print(f'Validated {len(p)} evaluation cases; relevance labels must be reviewed separately.')",
    ),
}


def run_task(task_id: str, timeout_seconds: int = 300) -> dict:
    """Run one allowlisted local validation task and return a redacted result."""
    if task_id not in ALLOWED_TASKS:
        return {
            "task_id": task_id,
            "status": "BLOCKED",
            "reason": "Task is not on the allowlist.",
        }
    if not 1 <= timeout_seconds <= 600:
        return {
            "task_id": task_id,
            "status": "BLOCKED",
            "reason": "timeout_seconds must be between 1 and 600.",
        }

    try:
        result = subprocess.run(
            ALLOWED_TASKS[task_id],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env={"PATH": __import__("os").environ.get("PATH", ""), "PYTHONUTF8": "1"},
        )
    except subprocess.TimeoutExpired:
        return {
            "task_id": task_id,
            "status": "FAIL",
            "reason": f"Task exceeded {timeout_seconds}s timeout.",
        }
    except OSError as exc:
        return {
            "task_id": task_id,
            "status": "FAIL",
            "reason": f"Could not start task: {type(exc).__name__}.",
        }

    # Output is intentionally not copied into the report to reduce the chance
    # of leaking credentials or document excerpts into persistent artifacts.
    return {
        "task_id": task_id,
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "exit_code": result.returncode,
        "stdout_lines": len(result.stdout.splitlines()),
        "stderr_lines": len(result.stderr.splitlines()),
    }


def run_plan(task_ids: Sequence[str], timeout_seconds: int = 300) -> dict:
    if not task_ids:
        raise ValueError("At least one task is required.")
    if len(task_ids) > MAX_TASKS_PER_RUN:
        raise ValueError(f"At most {MAX_TASKS_PER_RUN} tasks are allowed per run.")

    results = [run_task(task_id, timeout_seconds) for task_id in task_ids]
    statuses = {item["status"] for item in results}
    if "FAIL" in statuses:
        status = "FAIL"
    elif "BLOCKED" in statuses:
        status = "BLOCKED"
    else:
        status = "PASS"
    return {
        "schema_version": 1,
        "project": "StrategyG/RAG_Cerdas",
        "mode": "local_validation_only",
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "production_changes": False,
        "external_services_touched": False,
        "tasks": results,
        "limitations": [
            "No LLM planning or code repair is integrated.",
            "No Supabase or Dropbox connection is attempted.",
            "PASS means only the listed local checks passed; it does not prove RAG retrieval quality.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tasks", nargs="+", required=True, choices=sorted(ALLOWED_TASKS),
        help="Allowlisted local checks to run.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    try:
        report = run_plan(args.tasks, args.timeout_seconds)
    except ValueError as exc:
        parser.error(str(exc))

    serialized = json.dumps(report, indent=2, ensure_ascii=False)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
