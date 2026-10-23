from __future__ import annotations

import json

import pytest

from scripts import manager_governance as governance


def test_safe_action_is_allowed_without_executing():
    assert governance.classify_action("local_test") == "ALLOW"


@pytest.mark.parametrize(
    "action",
    [
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
    ],
)
def test_critical_actions_require_human_approval(action):
    assert governance.classify_action(action) == "REQUIRES_HUMAN_APPROVAL"


def test_unknown_action_is_blocked():
    assert governance.classify_action("run_arbitrary_shell") == "BLOCKED"


def test_request_action_records_decision_and_never_executes(tmp_path):
    ledger_path = tmp_path / "audit" / "manager-ledger.json"
    result = governance.request_action(
        ledger_path, "dropbox_delete", request_id="pilot-001"
    )
    assert result["decision"] == "REQUIRES_HUMAN_APPROVAL"
    assert result["executed"] is False
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["schema_version"] == 1
    assert ledger["entries"][0]["details"]["request_id"] == "pilot-001"
    assert ledger["entries"][0]["details"]["executed"] is False


def test_ledger_appends_events_atomically_and_preserves_order(tmp_path):
    path = tmp_path / "ledger.json"
    governance.append_event(path, "run_started", details={"run_id": "r1"})
    governance.append_event(path, "run_finished", details={"status": "PASS"})
    ledger = governance.load_ledger(path)
    assert [x["event"] for x in ledger["entries"]] == [
        "run_started", "run_finished"
    ]


def test_invalid_ledger_is_rejected(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text('{"schema_version": 99, "entries": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        governance.load_ledger(path)


def test_ledger_size_limit_is_enforced(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("x" * (governance.MAX_LEDGER_BYTES + 1), encoding="utf-8")
    with pytest.raises(ValueError, match="size limit"):
        governance.load_ledger(path)


def test_request_requires_request_id(tmp_path):
    with pytest.raises(ValueError, match="request_id"):
        governance.request_action(tmp_path / "ledger.json", "local_test", request_id=" ")
