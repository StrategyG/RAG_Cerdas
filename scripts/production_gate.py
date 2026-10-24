#!/usr/bin/env python3
"""Fail-closed, read-only release gate for Institutional RAG.

This script never connects to Supabase/Dropbox, applies migrations, deploys code,
or writes to the corpus. It inspects repository artifacts and an optional,
human-reviewed evidence manifest. Exit 0 means declared gates are complete;
it is not a substitute for independently verifying attached evidence.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "rag_pipeline.py",
    "eval_retrieval.py",
    "scripts/video_rag_worker.py",
    "docs/INSTITUTIONAL_RAG_PRODUCTION_AUDIT.md",
    "docs/INSTITUTIONAL_RAG_PRODUCTION_RUNBOOK.md",
    "docs/INSTITUTIONAL_RAG_RELEASE_GATES.md",
    "tests",
)
# These gates require evidence beyond CI. CI only proves the checks actually run
# by the workflow; it cannot establish correctness of live ingestion/retrieval.
REQUIRED_GATES = (
    "exact_commit_ci_passed",
    "source_validation_passed",
    "ingestion_idempotency_passed",
    "page_timestamp_correctness_passed",
    "retrieval_quality_and_citation_accuracy_passed",
    "canonical_schema_and_rpc_reviewed",
    "security_and_auth_reviewed",
    "backup_and_rollback_verified",
    "pdf_pilot_passed",
    "video_pilot_passed",
    "reviewed_eval_set_at_least_30",
    "retrieval_metrics_passed",
    "citation_and_grounding_passed",
    "abstention_tests_passed",
    "source_preservation_verified",
    "operations_recovery_verified",
    "human_review_signed_off",
    "approved_deployment_authorization",
)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read valid JSON: {exc}") from None


def inspect_eval_cases(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, "eval_cases.json missing"
    try:
        cases = load_json(path)
    except ValueError as exc:
        return False, f"eval_cases.json invalid: {exc}"
    if not isinstance(cases, list):
        return False, "eval_cases.json must contain a JSON list"
    reviewed = [
        case for case in cases
        if isinstance(case, dict)
        and case.get("label_status") in {"reviewed", "human_reviewed", "approved"}
        and isinstance(case.get("relevant_chunk_ids"), list)
        and len(case["relevant_chunk_ids"]) > 0
    ]
    if len(reviewed) < 30:
        return False, f"{len(reviewed)} human-reviewed cases with non-empty relevant_chunk_ids; require >= 30"
    return True, f"{len(reviewed)} reviewed cases with evidence labels"


def validate_evidence(path: Path, candidate_sha: str | None) -> tuple[bool, list[str]]:
    errors: list[str] = []
    try:
        manifest = load_json(path)
    except ValueError as exc:
        return False, [f"evidence manifest: {exc}"]
    if not isinstance(manifest, dict):
        return False, ["evidence manifest root must be an object"]
    sha = manifest.get("candidate_commit")
    if not isinstance(sha, str) or len(sha) != 40:
        errors.append("candidate_commit must be a full 40-character SHA")
    elif candidate_sha and sha.lower() != candidate_sha.lower():
        errors.append("evidence candidate_commit does not match --candidate-sha")
    gates = manifest.get("gates")
    if not isinstance(gates, dict):
        errors.append("gates must be an object containing explicit boolean results")
    else:
        for gate in REQUIRED_GATES:
            if gates.get(gate) is not True:
                errors.append(f"gate not passed: {gate}")
    evidence = manifest.get("evidence")
    if not isinstance(evidence, dict):
        errors.append("evidence must be an object with a reference for each gate")
    else:
        for gate in REQUIRED_GATES:
            value = evidence.get(gate)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"missing evidence reference: {gate}")
    return not errors, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-sha", help="full 40-character commit SHA under review")
    parser.add_argument("--evidence", type=Path, help="human-reviewed JSON evidence manifest")
    parser.add_argument("--run-tests", action="store_true", help="run pytest tests; no live integrations are invoked")
    args = parser.parse_args()

    failures: list[str] = []
    print("Institutional RAG production gate — READ-ONLY / FAIL-CLOSED")
    print("CI is necessary but insufficient; live data, quality, recovery, human review, and deployment approval need separate evidence.")
    print(f"Repository root: {ROOT}")

    for relative in REQUIRED_FILES:
        exists = (ROOT / relative).exists()
        print(f"[{'PASS' if exists else 'FAIL'}] required artifact: {relative}")
        if not exists:
            failures.append(f"required artifact missing: {relative}")

    eval_ok, eval_detail = inspect_eval_cases(ROOT / "eval_cases.json")
    print(f"[{'PASS' if eval_ok else 'BLOCK'}] reviewed evaluation set: {eval_detail}")
    if not eval_ok:
        failures.append(eval_detail)

    if args.run_tests:
        print("[INFO] Running pytest; this gate does not initiate database or Dropbox integration.")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--strict-config", "--strict-markers", "tests"],
                cwd=ROOT,
                check=False,
            )
            if result.returncode:
                failures.append(f"pytest exited with code {result.returncode}")
                print(f"[FAIL] pytest exit code {result.returncode}")
            else:
                print("[PASS] pytest")
        except OSError as exc:
            failures.append(f"could not run pytest: {exc}")
            print(f"[FAIL] pytest could not run: {exc}")
    else:
        print("[INFO] Tests not run (pass --run-tests to execute the local test suite).")

    if args.evidence:
        evidence_ok, evidence_errors = validate_evidence(args.evidence, args.candidate_sha)
        if evidence_ok:
            print("[PASS] evidence manifest: all declared gates and references are present")
        else:
            for error in evidence_errors:
                print(f"[BLOCK] evidence manifest: {error}")
                failures.append(error)
    else:
        print("[BLOCK] no evidence manifest supplied; live pilot, security, recovery and quality gates remain unproven")
        failures.append("missing human-reviewed evidence manifest")

    if failures:
        print(f"\nDECISION: NO-GO for production ({len(failures)} blocker(s)).")
        print("A successful local test run alone cannot promote this system to production.")
        return 2

    print("\nDECISION: GATES DECLARED COMPLETE. Independently review evidence and obtain explicit deployment approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
