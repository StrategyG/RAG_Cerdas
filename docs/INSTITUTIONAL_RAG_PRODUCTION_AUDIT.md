# Institutional RAG Production Audit

**Audit date:** 2026-10-24  
**Repository:** `StrategyG/RAG_Cerdas`  
**Working branch:** `fix/video-rag-safe-generation`  
**Pull request:** [#9](https://github.com/StrategyG/RAG_Cerdas/pull/9)  
**Decision:** **NO-GO for production; PILOT ONLY after schema and integration gates pass.**

## Scope and evidence

This audit used GitHub repository file reads and read-only Supabase project queries for project ref `uktauwysjkseqrnbjwzy`. No database migration was applied, no Edge Function was deployed, no source files were downloaded, and no ingestion was run as part of this audit. GitHub file reads succeeded for the branch's video worker, retrieval migration, Edge Function, and CI workflow. Some paths under `docs/` did not exist at audit time.

## Executive findings

| Area | Status | Severity | Evidence / impact |
|---|---|---:|---|
| Canonical schema | FAIL | Critical | Both `rag` and `institutional_rag` contain live corpus tables. The video worker and Edge Function route through `rag`; the other schema has a separate source/chunk model and lexical RPC. Ownership and migration strategy must be documented before expanding ingestion. |
| Corpus indexing | FAIL | Critical | Live counts: `rag.documents` = 352 discovered, 31 failed; `rag.chunks` = 25,343, all 25,343 embeddings NULL. `institutional_rag.source_documents` = 298 discovered, 2 chunked; `document_chunks` = 5, all embeddings NULL. No verified production-ready retrieval corpus. |
| PDF provenance | FAIL | Critical | All 25,343 `rag.chunks` have `page_start IS NULL` in the observed live snapshot. Citation-safe PDF retrieval intentionally excludes these legacy chunks. |
| Evaluation | FAIL | High | `institutional_rag.evaluation_cases` and `evaluation_results` were reported as zero rows in the current live schema snapshot. No reviewed gold set is available to establish retrieval quality. |
| Lexical language | FAIL | High | `rag.chunks.search_vector` is generated with `to_tsvector('english', ...)`; `institutional_rag.document_chunks.search_vector` uses `simple`. The video migration's query parser uses `english` to match the current `rag` generated vector. This is internally consistent for that path but does not prove adequate Indonesian recall. |
| Retrieval RPC contract | PASS with caveat | High | Live `public.rag_worker_match_keyword(text, integer, double precision)` is `SECURITY DEFINER`, empty search path, and delegates to `rag.match_chunks_keyword`. Its grants and caller authorization must remain verified during release review. |
| Edge Function runtime | BLOCKED | Critical | `institutional-rag-search` is ACTIVE, version 1, with `verify_jwt=false`. The code implements a custom `x-rag-api-key` check, but secret presence/rotation and unauthorized live-request behavior were not tested. Do not change deployment or auth settings during this audit. |
| Video worker | NOT TESTED end-to-end | High | Code supports one-video runs, Dropbox download byte ceiling, timestamp chunks, 384D finite embedding validation, and append-only generation metadata. No actual Dropbox video was downloaded or transcribed in this audit. |
| Migration deployment | BLOCKED | High | Live migration history ended at `20261023200123 video_rag_model_alignment`; branch migration `20261024090000_video_timestamp_keyword_retrieval.sql` is not present in the live history. Do not apply until the full live function contract and permissions are reviewed. |
| CI / candidate commit | PASS (repository checks only) | High | Workflow run [#40094400731](https://github.com/StrategyG/RAG_Cerdas/actions/runs/40094400731) completed successfully for candidate commit `0cd1ea3bcf5150933c6672452b11dabfbd2d9eca`: Python compilation, 110 pytest tests, video citation regex contract, and evaluation-case schema check passed. This does not verify live DB, Dropbox, Edge Function, or RAG quality. |
| Dropbox incremental sync | NOT TESTED | High | No live Dropbox API enumeration/cursor or file metadata validation was run. Worker requires `rag.documents.metadata.dropbox_id` for video discovery. |
| Security / RLS | FAIL / PARTIAL | High | RLS is enabled on both schemas. Explicit deny policies exist on the four observed `rag` tables, but Supabase security advisors report five `institutional_rag` tables with RLS enabled and no policies. This is default-deny for those API roles, but intended access and all grants/schema exposure still need review. |

## Live corpus snapshot

Read-only query results observed on 2026-10-24:

- `rag.documents`: 383 total — 352 `discovered`, 31 `failed`.
- `rag.chunks`: 25,343 total — 25,343 embeddings NULL; prior live audit also reported page provenance NULL for all rows.
- `institutional_rag.source_documents`: 300 total — 298 `discovered`, 2 `chunked`.
- `institutional_rag.document_chunks`: 5 total — 5 embeddings NULL.
- Evaluation tables: no cases/results reported in the prior/current audit context.

Counts are a snapshot, not a durable invariant; rerun the read-only audit before each release decision.

## Root causes and required repairs

1. **Two schema tracks:** determine one canonical ingestion/retrieval path. Current runtime worker and Edge Function use `rag`; do not move or delete `institutional_rag` data. Create a compatibility plan before any consolidation.
2. **Legacy chunks are not citation-safe:** reprocess a single permitted PDF into an additive page-aware generation; verify source page mapping and active-generation filtering before considering backfill.
3. **Embeddings are absent:** establish a pilot embedding contract and query-embedding compatibility. Do not claim semantic retrieval until the vector path is actually exercised.
4. **Language mismatch risk:** benchmark Indonesian and English queries against reviewed labels. Consider a new generated column/index or a separate lexical strategy only after measured comparisons; do not change live schema during this audit.
5. **Release evidence is incomplete:** create at least 30 human-reviewed evaluation cases, run retrieval and citation tests, and preserve raw outputs and commit SHA.
6. **Edge auth risk:** `verify_jwt=false` means the custom API-key boundary is security-critical. Verify secret presence without printing it; test unauthorized and authorized requests in a controlled environment before deployment.
7. **Video worker operational gaps to test:** stale-lease recovery, retry limits, transaction/activation consistency, duplicate-run behavior, and error redaction need explicit integration evidence. The worker validates transcript timestamps for finite values, monotonic starts, valid ranges, non-empty text, and known duration bounds. The Edge Function now additionally rejects timestamp citations whose end is not strictly after the start; a Node contract regression assertion was added. CI for the latest code/test changes was queued at workflow run [#40094804217](https://github.com/StrategyG/RAG_Cerdas/actions/runs/40094804217) and must be checked again before release.

## Facts, assumptions, unknowns

**Facts:** live schema/table counts and column definitions came from read-only Supabase queries; active Edge Function metadata reports `verify_jwt=false`; the live wrapper is `SECURITY DEFINER` with an empty search path; branch files were read from GitHub.

**Assumptions:** none are treated as release evidence. The branch worker is expected to use the current `rag` schema based on its SQL and the retrieved source.

**Unknown / not verified:** secret existence/rotation, actual Dropbox cursor state, current runtime response for authorized/unauthorized requests, real PDF/video pilot, embedding retrieval, citation accuracy, latency, backup restore, and rollback execution. The repeatable read-only SQL audit was added at `supabase/verification/institutional_rag_production_audit.sql`; it is included in the CI file-presence check but has not been executed against a separate non-production database.

## Release status

**NO-GO for production. PILOT ONLY** after the migration/RPC contract is reviewed and controlled PDF/video pilot tests pass. No bulk ingestion, live migration, Edge Function deployment, or access-policy change is authorized by this audit.
