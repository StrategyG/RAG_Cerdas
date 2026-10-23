from __future__ import annotations

import json

import pytest

from scripts import autonomous_manager as manager


def test_unknown_task_is_blocked_without_execution(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("subprocess must not run for an unknown task")

    monkeypatch.setattr(manager.subprocess, "run", unexpected)
    result = manager.run_task("ingest_supabase")
    assert result["status"] == "BLOCKED"
    assert "allowlist" in result["reason"]


def test_task_limit_is_enforced():
    with pytest.raises(ValueError, match="At most"):
        manager.run_plan(["compile"] * (manager.MAX_TASKS_PER_RUN + 1))


def test_empty_plan_is_rejected():
    with pytest.raises(ValueError, match="At least one task"):
        manager.run_plan([])


def test_invalid_timeout_is_blocked(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("subprocess must not run with invalid timeout")

    monkeypatch.setattr(manager.subprocess, "run", unexpected)
    result = manager.run_task("compile", timeout_seconds=0)
    assert result["status"] == "BLOCKED"


def test_run_task_reports_only_summary_and_redacts_output(monkeypatch):
    class FakeResult:
        returncode = 0
        stdout = "passed\nsecret-like-output\n"
        stderr = ""

    monkeypatch.setattr(manager.subprocess, "run", lambda *a, **k: FakeResult())
    result = manager.run_task("compile")
    assert result["status"] == "PASS"
    assert result["stdout_lines"] == 2
    assert "secret-like-output" not in json.dumps(result)


def test_run_plan_reports_no_production_changes(monkeypatch):
    monkeypatch.setattr(
        manager,
        "run_task",
        lambda task_id, timeout_seconds: {"task_id": task_id, "status": "PASS"},
    )
    report = manager.run_plan(["compile", "eval_schema"])
    assert report["status"] == "PASS"
    assert report["production_changes"] is False
    assert report["external_services_touched"] is False
    assert report["mode"] == "local_validation_only"
    assert any("No LLM planning" in item for item in report["limitations"])


def test_failure_propagates_to_plan_status(monkeypatch):
    monkeypatch.setattr(
        manager,
        "run_task",
        lambda task_id, timeout_seconds: {"task_id": task_id, "status": "FAIL"},
    )
    assert manager.run_plan(["compile"])["status"] == "FAIL"
