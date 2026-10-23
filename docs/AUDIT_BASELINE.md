# Institutional RAG — Audit Baseline

**Audit date:** 2026-10-23  
**Scope:** Read-only GitHub repository/branch and source inspection. No Supabase or Dropbox live connection was attempted in this audit pass.  
**Target:** `codespaces-institutional-rag`; production/default branch `main`.  
**Baseline status:** **MODIFY / NOT PRODUCTION-READY**.

## Evidence classification

- **Verified from GitHub API/source:** branch comparison, fetched source files, workflow configuration, migration text, evaluation cases.
- **Static finding:** issue inferred from code/configuration; not proof that an exploit or runtime failure occurred.
- **Not verified:** requires active Codespaces runtime, GitHub secret metadata/permissions, or read-only Supabase/Dropbox access.

## Branch and integration state

| Item | Finding | Status |
|---|---|---|
| Default branch | `main`, head `0d3b65e21f82d35ca5313418fed86b248f61fe3f` | Verified |
| Development branch | `codespaces-institutional-rag` | Verified |
| Comparison | Development is **87 commits ahead, 0 behind**; comparison reports 87 commits total | Verified |
| Diff scope | Adds RAG pipeline/evaluation, Codespaces config, tests, docs, multiple Supabase migrations and a WhatsApp gateway; review files individually before integration | Verified |
| Open PR search | Repository-scoped open PR search returned no results; connector search result is not sufficient to prove no PR exists under every query shape | Partially verified |
| Direct changes to `main` | None made | Verified |

## Findings

### P0 — release blockers

1. **Live database/schema compatibility is not verified.** Worker code calls named RPCs and assumes columns/JSON contracts in `rag_pipeline.py`; migration SQL creates/changes these contracts. No live read-only schema/RPC check was run. A passing unit suite cannot establish that migrations are applied or that production schema matches.
   - Evidence: `rag_pipeline.py`, `supabase/migrations/20261018182702_claim_ingest_jobs_only.sql`, `supabase/migrations/20261020055818_append_only_ingestion_generations.sql`, `supabase/verification/verify_ingestion_state.sql`.
   - Impact: ingestion may fail or behave differently if migration state/schema differs.
   - Next: inspect migration history and run only approved read-only verification SQL; do not apply migrations in this audit.

2. **Archive workflow extracts an untrusted repository tarball without path validation.** `.github/workflows/extract-workspace.yml` on `main` runs `tar -tzf ... | head -200` under `set -o pipefail`, then extracts archive entries directly. The listing pipeline can fail from SIGPIPE on large archives; archive paths are not checked for absolute paths or traversal before extraction.
   - Classification: static security/reliability finding; no malicious archive or actual failure was executed.
   - Impact: unreliable workflow and potential path traversal during extraction of an untrusted archive.
   - Next: inspect archive members in Python without extracting, reject absolute/parent traversal paths and unsafe links, then extract into a fresh isolated directory; avoid `tar | head` and `find | head`.

3. **Secret and live integration status is unknown.** `.devcontainer/devcontainer.json` declares secret names, but this is configuration guidance—not evidence that values are configured or injected into the active Codespace. The code supports read-only preflight, but it was not run against live services.
   - Impact: Dropbox/Supabase integration cannot be called connected.
   - Next: run `python scripts/preflight.py` inside the actual Codespace and report only status codes/boolean presence, never secret values.

### P1 — evaluation and CI/release blockers

4. **Gold relevance labels are absent.** `eval_cases.json` has 3 cases (Q001–Q003) and each has an empty `relevant_chunk_ids` mapping. The workflow explicitly reports unlabeled cases as unscored. Recall/MRR/nDCG cannot be meaningfully measured until human-reviewed qrels exist.
   - Impact: no valid measured retrieval-quality claim; the requested 30-case gold set is not present.
   - Next: preserve current cases as a draft/template and label against retrieved corpus evidence with human review.

5. **Development branch is not integrated with production.** The development branch adds 87 commits and multiple migrations/workflows. Do not merge the entire branch wholesale without reviewing the file-level diff and migration sequence.
   - Next: small, reviewable PRs with required CI and migration review.

6. **CI is not equivalent to end-to-end RAG validation.** `.github/workflows/rag-tests.yml` runs lightweight tests and schema-shape checks; its test dependency set omits heavyweight embedding/runtime integration and intentionally needs no production secrets. This is appropriate for safe CI, but does not prove live retrieval, embedding persistence, answer generation, or citations.
   - Next: separate mock-based CI from opt-in isolated integration tests.

7. **Dependency reproducibility is incomplete.** `requirements.txt` and `requirements-test.txt` use version ranges; no `pyproject.toml` or lockfile was found at the inspected development-branch paths.
   - Impact: future builds may resolve different transitive dependencies.
   - Next: add a reviewed constraints/lock strategy without unnecessarily pinning incompatible platform-specific packages.

### P2 — product/operational gaps

8. **README missing on inspected development branch.** Fetch of `README.md` returned 404; `CODESPACES_RAG_SETUP.md` and docs provide partial setup guidance.
   - Next: add a root README after the baseline, documenting safe setup, dry-run, tests, recovery, and known limitations.

9. **Answer-generation end-to-end path is not established by inspected files.** `eval_retrieval.py` evaluates keyword and semantic retrieval and exports result excerpts; this alone does not prove grounded answer generation, citation validation, contradiction handling, or abstention behavior.
   - Next: treat generation/citation validation as a separate P2 feature with acceptance tests.

10. **Historical readiness figures are not current live metrics.** `docs/PRODUCTION_READINESS_GATE.md` contains a blocked readiness snapshot, but no live database query was executed during this audit.
    - Next: run read-only verification SQL from the authorized environment and timestamp its output.

## Files inspected

- `main`: `.github/workflows/extract-workspace.yml`.
- `codespaces-institutional-rag`: `rag_pipeline.py`, `eval_retrieval.py`, `eval_cases.json`, `requirements.txt`, `requirements-test.txt`, `.github/workflows/rag-tests.yml`, `.devcontainer/devcontainer.json`, `.devcontainer/post-create.sh`, `.gitignore`, `scripts/preflight.py`, `scripts/supabase_http.py`, `supabase/migrations/20261018182702_claim_ingest_jobs_only.sql`, `supabase/migrations/20261020055818_append_only_ingestion_generations.sql`, `supabase/verification/verify_ingestion_state.sql`, `tests/test_pipeline_dry_run.py`, `tests/test_versioned_ingestion_contract.py`, `docs/PRODUCTION_READINESS_GATE.md`, `docs/DROPBOX_CODESPACES_CONNECT.md`.
- Root `README.md` and `pyproject.toml` fetches on the development branch returned 404.

## Secrets, services, and runtime verification

| Check | Status | Evidence |
|---|---|---|
| Secret names declared in devcontainer | PASS | Three variable names documented; values were not read |
| Secret values present in active Codespace | NOT TESTED | No Codespaces terminal/session access in this pass |
| Dropbox read-only authentication/download | NOT TESTED | No live request made |
| Supabase read-only RPC/schema verification | NOT TESTED | No live request made |
| Migration applied to target database | NOT TESTED | No database migration-history query made |
| Current chunks/embeddings/page mappings/active generation | NOT TESTED | No live database query made |
| Current CI run output | NOT TESTED in this audit record | Source workflow inspected; historical test evidence must be checked against run/job logs before reuse |

## Initial repair order

1. Keep `main` unchanged. Preserve this baseline as a committed audit artifact on the development branch.
2. P0: harden archive inspection/extraction on a separate reviewable branch or a dedicated PR; no archive execution.
3. P0: run read-only schema/RPC verification from an authorized Codespace; no migration or data writes.
4. P0: verify secret presence and read-only Dropbox/Supabase preflight without revealing values.
5. P1: inspect CI run logs and run the available test suite; fix only failures supported by evidence.
6. P1: build a human-labeled evaluation set; do not fabricate relevance labels.
7. P2: README and end-to-end answer/citation validation.
8. Pilot exactly one explicitly selected PDF only after preflight, dry-run, schema compatibility, and owner approval.

## Decision

**MODIFY.** The branch contains a promising page-aware, versioned ingestion foundation and tests, but the evidence collected here is insufficient for production approval. Do not run bulk ingestion, apply migrations, change RLS, or merge to `main` until the P0 gates are satisfied.
