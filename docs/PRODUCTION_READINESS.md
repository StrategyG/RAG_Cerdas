# Institutional RAG — Production Readiness Assessment

**Assessment date:** 2026-10-23  
**Repository:** `StrategyG/RAG_Cerdas`  
**Assessment branch:** `codespaces-institutional-rag`  
**Default/production branch:** `main`  
**Decision:** **MODIFY — NOT PRODUCTION-READY**

## Evidence boundary

This assessment is based on GitHub repository source and branch comparison. It is not a live Codespaces, Supabase, or Dropbox health check. Tests and integrations are only marked PASS when their execution evidence is available. The latest source changes below have not yet been run by the repository test runner.

## Current branch state

- `main` head at the compared base: `0d3b65e21f82d35ca5313418fed86b248f61fe3f`.
- The development branch is **94 commits ahead, 0 behind** `main`.
- Do not merge the branch as a whole. It contains RAG pipeline work, migrations, workflows, tests, and a WhatsApp gateway; review and stage the diff by feature and risk.
- No changes to `main`, live database writes, migrations, mass ingestion, deployment, or Dropbox source mutation were performed during this assessment.

## Gate status

| Gate | Status | Evidence / blocker |
|---|---|---|
| A — Security | **PARTIAL / NOT VERIFIED** | PDF path containment hardening and archive validation code are present; tests and workflow have not run in GitHub Actions. Access control/RLS has not been verified against the live database. |
| B — Data integrity | **NOT VERIFIED** | Source code includes page-aware/versioned ingestion concepts, but live schema compatibility, idempotency against real data, and page mappings have not been demonstrated in this run. |
| C — Retrieval quality | **BLOCKED** | `eval_cases.json` contains 3 draft cases with empty `relevant_chunk_ids`; valid Recall/MRR/nDCG are not measured. |
| D — Grounded answers and citations | **NOT VERIFIED** | Retrieval evaluation does not by itself prove answer generation, citation page accuracy, contradiction handling, or abstention. |
| E — Operational reliability | **NOT VERIFIED** | Backup/restore, retry behavior, stuck-job recovery, observability, and a live pilot have not been demonstrated. |
| F — Release/deployment safety | **BLOCKED** | 94-commit branch diff requires file-level review; tests after latest changes and migration review are outstanding. |

## Verified code-level work

1. `rag_pipeline.py` resolves local PDF paths and rejects resolved paths outside the configured PDF directory.
2. `tests/test_pdf_source_path_safety.py` contains parent traversal and external symlink regression tests.
3. `scripts/validate_workspace_archive.py` validates archive member paths/types, rejects links and special entries, detects duplicates and file/directory conflicts, enforces member/size limits, and extracts regular files/directories only.
4. `tests/test_workspace_archive_validator.py` adds fixtures for valid extraction, traversal, absolute paths, backslashes, symlinks, duplicate paths, file/directory conflicts, and existing destinations.
5. `.github/workflows/extract-workspace.yml` calls the validator module instead of embedding archive extraction logic inline.

These are source inspection findings. The changes are **implemented but not yet test-verified** in a repository runner.

## Test and integration status

| Check | Status |
|---|---|
| GitHub branch comparison | PASS — 94 ahead, 0 behind |
| Source inspection | PASS — files fetched from development branch |
| PDF path regression tests | NOT RUN |
| Archive validator tests | NOT RUN |
| Full pytest suite | NOT RUN after latest changes |
| GitHub Actions run for latest commits | NOT VERIFIED |
| Actual Codespaces preflight | NOT RUN |
| Supabase read-only schema/RPC/migration-history check | NOT RUN |
| Dropbox read-only source verification | NOT RUN |
| Embedding persistence and vector retrieval | NOT VERIFIED |
| Page-correct citations and grounded answer tests | NOT VERIFIED |
| Backup/restore and rollback rehearsal | NOT RUN |
| Production release | NO-GO |

## Mandatory next actions

1. In Codespaces, verify the branch and worktree:
   ```bash
   git branch --show-current
   git status --short
   ```
2. Run the complete current test suite:
   ```bash
   python -m pytest -q --strict-config --strict-markers tests
   python -m py_compile rag_pipeline.py eval_retrieval.py scripts/preflight.py scripts/validate_workspace_archive.py
   bash -n .devcontainer/post-create.sh
   ```
3. Inspect the GitHub Actions run for the exact commit SHA; report failures rather than assuming the workflow ran.
4. Run `python scripts/preflight.py` only from the authorized Codespace. Report status only; never print secret values.
5. Inspect and run only the approved read-only SQL in `supabase/verification/verify_ingestion_state.sql` after confirming compatibility with the actual schema. Do not apply migrations.
6. Build a human-reviewed gold set of at least 30 questions and evidence labels. Do not fabricate chunk IDs or relevance labels.
7. After all static tests and preflight pass, request approval for a single-document pilot. Verify backup/recovery before any database write.

## Release rule

**Do not declare production readiness until all six gates pass with evidence.** Do not perform bulk ingestion, re-indexing, data resets, migration execution, RLS changes, merge to `main`, or deployment as part of this assessment.
