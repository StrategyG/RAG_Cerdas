# Institutional RAG — Repair Report (Checkpoint)

**Date:** 2026-10-23  
**Repository:** `StrategyG/RAG_Cerdas`  
**Working branch:** `codespaces-institutional-rag`  
**Production/default branch:** `main`  
**Decision:** **MODIFY — not production-ready**  
**Scope:** Phase A baseline completed; limited, non-destructive P0 code hardening performed. No database migration, live ingestion, Dropbox write, Supabase write, deployment, or merge to `main` was performed.

## 1. Executive summary

The development branch is 87 commits ahead of `main` and 0 behind. A read-only baseline was committed before code edits. Two static P0 risks were then addressed on the development branch:

1. Local PDF resolution now resolves paths and rejects files whose resolved path escapes the configured PDF directory, including external symlinks.
2. The archive workflow no longer uses `tar | head` / `find | head`, rejects absolute/traversal paths, rejects links and special archive members, checks duplicate paths, caps member count and declared uncompressed size, and writes only regular files/directories into a fresh extraction directory.

A regression test file was added for path traversal and external symlinks. It has **not yet been executed in the repository environment**. The archive validator's Python body was syntax-checked in an isolated Python check, but the GitHub workflow itself has not been run. No claim of live connectivity or production readiness is made.

## 2. Initial baseline

- Audit artifact: `docs/AUDIT_BASELINE.md`
- Baseline commit: `04a4c31c1174e674fdcafb0c9802a17f989a3a72`
- Branch comparison: `codespaces-institutional-rag` ahead by 87 commits, behind by 0.
- Gold evaluation data: 3 cases, each with an empty `relevant_chunk_ids` mapping.
- Root `README.md` was not present at the inspected development-branch path.
- Historical CI run `39378213308` completed successfully before these repair commits; its reported 17 passing tests do not verify the new changes or live integration.

## 3. Changes made

| File | Change | Commit | Status |
|---|---|---|---|
| `docs/AUDIT_BASELINE.md` | Recorded branch state, findings, evidence classes, unknowns, and repair order before code changes | `04a4c31c1174e674fdcafb0c9802a17f989a3a72` | PASS — committed |
| `rag_pipeline.py` | Resolve local PDF paths and enforce containment under `PDF_DIR`; filter out resolved matches outside that root | `f5d8c328ce0c0cada738ead808c992fbfc641d35` | Implemented; test pending |
| `tests/test_pdf_source_path_safety.py` | Added tests for parent traversal and external symlink resolution | `bd36726d0f3a8f64efe69d6f9085f58b30bacf39` | Added; not run |
| `.github/workflows/extract-workspace.yml` | Replaced truncating shell pipelines and direct archive extraction with path/type/size validation and controlled extraction | `3a6907829903b4c71754e24030bb3d5b2f13d044` | Implemented; workflow not run |
| `.github/workflows/extract-workspace.yml` | Corrected manifest line endings | `a44ff1b6ae0934fb43178b4b4b3d8ebd4fa0cb7a` | Implemented |
| `.github/workflows/extract-workspace.yml` | Corrected archive validator indentation | `abbd2cc6ef7181df6160c269add143cd58b7f90d` | Implemented |

No files were changed on `main`.

## 4. Tests and actual outputs

| Check | Result | Evidence / limitation |
|---|---|---|
| Read-only branch comparison | PASS | GitHub compare: 87 ahead, 0 behind |
| Source and workflow inspection | PASS | Files fetched from both branches; see audit baseline |
| Archive validator Python syntax check | PASS | Isolated `ast.parse` check printed `Archive workflow Python body: syntax PASS`; not a GitHub Actions run |
| New PDF path safety regression tests | NOT TESTED | Tests are committed but no repository runner was available in this operation |
| Full pytest suite after changes | NOT TESTED | Historical run predates these commits |
| Archive workflow execution | NOT TESTED | Workflow has `workflow_dispatch`; no manual dispatch was performed |
| Live Supabase read-only schema/RPC check | NOT TESTED | No active Codespaces terminal or database query performed |
| Live Dropbox metadata/download check | NOT TESTED | No active Codespaces terminal or Dropbox request performed |
| Ingestion/embedding/citation pilot | BLOCKED | Requires verified live credentials, schema compatibility, preflight and explicit pilot selection |
| Retrieval metrics | BLOCKED | Human-reviewed relevance labels are absent |
| Production deployment / merge | NOT PERFORMED | Intentionally withheld |

The GitHub connector did not return workflow runs for the latest repair commits through its commit-run query, which only surfaces pull-request-triggered runs. Therefore this report does not infer that push-triggered CI passed or failed.

## 5. Remaining blockers and risks

### P0
- Execute the full unit suite against the current branch and inspect the current push-triggered CI result.
- From the actual Codespace, run the read-only preflight and report only status/boolean values; never print secrets.
- Verify actual Supabase migration history, schema, RPC signatures and privileges using approved read-only queries.
- Confirm whether migration files in the development branch have been applied; do not apply them as part of connectivity verification.
- Run a malicious-archive fixture test and a safe-archive fixture test against the exact workflow validator before relying on archive extraction.

### P1
- Add human-reviewed labels for at least 30 evaluation cases based on real corpus chunks; do not infer labels from the system's own results.
- Add or update root `README.md` and define a reproducible dependency constraints/lock strategy.
- Review all 87 commits and migrations in small PRs; do not open a PR that implicitly treats the whole branch as production-ready.
- Confirm required branch protection/status checks in GitHub settings; repository policy was not inspected by the available read-only source calls.

### P2/P3
- Validate end-to-end answer generation, citations, abstention and conflicting evidence separately from retrieval.
- Test recovery and rollback in an isolated/staging database before a one-PDF live pilot.
- Keep video audio transcription separate from OCR/visual understanding.

## 6. Dropbox and Supabase status

- **Dropbox:** NOT TESTED — no verified connection claim.
- **Supabase:** NOT TESTED — no verified connection or schema compatibility claim.
- **Secrets:** variable names are declared in Codespaces configuration, but the actual secret values and their availability in the active Codespace were not inspected.

## 7. Cost

No paid service was added and no live model/database operation was run during this checkpoint. Actual operational cost is therefore **not measured**. Existing dependency/model download, Codespaces usage, and Supabase limits still need to be assessed in the real environment.

## 8. Next steps from Android via Codespaces

1. Open the repository and select `codespaces-institutional-rag`.
2. Confirm branch and working tree with `git branch --show-current` and `git status --short`.
3. Run `python -m pytest -q --strict-config --strict-markers tests` and inspect the current GitHub Actions run.
4. Run `python scripts/preflight.py`; report only whether required variables are set and whether the read-only checks pass. Never print token values.
5. Run only the documented read-only SQL in `supabase/verification/verify_ingestion_state.sql` after checking it against the actual schema. Do not apply migrations or write data at this stage.
6. Test archive validation with safe and malicious fixtures before manually dispatching the archive workflow.
7. Only after these gates pass, choose one explicitly authorized PDF and proceed through preflight, dry-run, ingestion, embedding and manual citation verification.

## 9. Final checkpoint decision

**MODIFY.** The two static P0 code risks have been addressed in the development branch, but the code and workflow changes remain unverified by the repository test runner. Live Dropbox/Supabase access, database compatibility, gold evaluation metrics, answer/citation quality, recovery testing and release controls remain open. Do not run bulk ingestion, change RLS, apply production migrations, merge to `main`, or declare production readiness.


## 9. Follow-up hardening (2026-10-23)

A fresh GitHub compare after the follow-up changes reports the development branch **94 commits ahead, 0 behind** `main`. This is the current comparison; the earlier 87-commit figure above describes the earlier checkpoint and is retained as historical context.

Additional source changes made after that checkpoint:

| File | Change | Commit | Verification |
|---|---|---|---|
| `scripts/validate_workspace_archive.py` | Extracted archive validation into a reusable module; validates all members before creating destination; rejects traversal/absolute/ambiguous paths, backslashes, links/special entries, duplicate paths and file/directory conflicts; enforces member and uncompressed-size limits | `88a18e424cd0e8179fb352a640e8d4edcdc8223d` | Implemented; tests not run |
| `tests/test_workspace_archive_validator.py` | Added valid archive and unsafe archive fixtures including traversal, absolute path, backslash, symlink, duplicate entry, file/directory conflict, and pre-existing destination | `12bfc51566a519b102e7c4f87977e64f719a78cc` | Added; tests not run |
| `.github/workflows/extract-workspace.yml` | Workflow now invokes the reusable validator module | `cfe9af46ccb65b183b3dae5c8f1505f34e5fdb31` | Source updated; workflow not run |
| `docs/PRODUCTION_READINESS.md` | Added current evidence-based gate assessment and release blockers | `dedc875e13c1b76eb7937ce1a663bd2451286c49` | Committed; reflects known evidence boundary |

No GitHub Actions run was manually dispatched. No tests were executed in the repository runtime during this follow-up. No live Supabase or Dropbox requests, database writes, migration, bulk ingestion, deployment, or change to `main` occurred.

### Remaining verification

- Run `python -m pytest -q --strict-config --strict-markers tests` in the actual Codespace and inspect the exact GitHub Actions run for the current commit.
- Run the archive validator fixture tests and review any failures before relying on the workflow.
- Verify live connectivity and schema only through authorized read-only checks.
- Keep retrieval metrics marked `NOT MEASURED` until human-reviewed relevance labels exist.
