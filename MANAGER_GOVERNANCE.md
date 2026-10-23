# Manager governance pilot

## Scope

`scripts/manager_governance.py` provides a small persistent JSON audit ledger and
a conservative action classifier for the Institutional RAG manager.

- Local read-only checks, local tests, and local dry-runs are allowlisted.
- Merge-to-main, Supabase writes/migrations/RLS changes, Dropbox writes/moves/deletes/sharing changes, deployment, paid API calls, and external data transfer require human approval.
- Unknown actions are blocked.
- The module records decisions only. It never executes the requested action.

## Run a local policy check

```bash
python scripts/manager_governance.py \
  --ledger .local/manager-ledger.json \
  --request-action dropbox_delete \
  --request-id pilot-001
```

The command exits with code 2 for a request that requires approval or is blocked.
Do not commit `.local/manager-ledger.json`; it may contain operational metadata.

## Security limitation

The JSON ledger is not tamper-proof and does not authenticate the approver. A local
flag or editable JSON file is not sufficient authorization for consequential work.
Critical actions remain non-executable in this pilot. Before any such action can
run, integrate an authenticated approval mechanism (for example, a protected GitHub
Environment with required reviewers) and verify the approval in the execution
workflow. Never store tokens or secrets in the ledger.

## Validation boundary

Passing tests verifies only this local policy and ledger module. It does not prove
Supabase/Dropbox connectivity, RAG ingestion, retrieval quality, citation correctness,
or production readiness.
