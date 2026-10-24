# Institutional RAG Production Runbook

## Safety contract

- Dropbox originals are read-only. Never rename, move, overwrite, or delete source files.
- Do not run a corpus-wide scan or bulk ingestion until both pilot sources and the reviewed evaluation gate pass.
- Do not apply Supabase migrations, deploy Edge Functions, modify RLS/grants, or change live secrets as part of routine diagnosis.
- Never print credentials, full authorization headers, database URLs, or secret values.
- Preserve old chunks and generations. Build new data additively; activate only after integrity checks succeed.

## Current architecture snapshot

The observed live project has two data tracks: `rag.documents / rag.chunks` and `institutional_rag.source_documents / institutional_rag.document_chunks`. The current video worker and `institutional-rag-search` use the `rag` track and `public.rag_worker_match_keyword`. Do not ingest through both tracks. The production audit must explicitly approve a canonical path before any scale-up.

The Edge Function currently reports ACTIVE with `verify_jwt=false` and uses a custom `x-rag-api-key` check in code. Treat that key as a critical security boundary; do not disable or bypass it. The current endpoint uses keyword retrieval, not proven hybrid/semantic retrieval.

## Read-only preflight

Before any pilot, capture:

1. Repository branch, commit SHA, PR head SHA, and latest CI conclusion.
2. Live migration history and current function signatures/definitions/grants.
3. Table counts by status; chunks missing page/timestamp provenance; null/invalid embeddings.
4. Active generation IDs and counts per generation.
5. RLS policies, table grants, function execution grants, Edge Function auth configuration.
6. Dropbox source metadata availability for the chosen pilot IDs without changing originals.

Record timestamp and project ref in the report. Avoid recording secrets or source text that is not necessary.

## Controlled PDF pilot

1. Select one authorized, text-based PDF and record Dropbox file ID, metadata, size, modified time, and source hash where feasible.
2. Download to a temporary directory with a configured size ceiling and timeouts. Use read-only API scope; do not mutate the Dropbox file.
3. Extract text page-by-page. Preserve original 1-based page numbers. If extracted text is empty, classify as scanned/unsupported and stop unless OCR is explicitly configured and tested.
4. Chunk only within page boundaries or store exact start/end page provenance.
5. Generate embeddings with an explicitly pinned model; validate dimensions and finite values.
6. Write into a new generation in a transaction. Do not delete legacy rows.
7. Verify chunk counts, page bounds, hash, model name, vector dimensions, active-generation metadata, and database retrieval.
8. Run known-answer and no-evidence questions; verify every citation points to the actual source and page.
9. Repeat the same job and verify it does not duplicate or prematurely activate data.
10. Keep the generation inactive if any check fails.

## Controlled video pilot

1. Select one authorized video; record Dropbox ID, metadata, file size, and hash after download.
2. Enforce a byte ceiling and connect/read timeouts. Keep temporary files outside persistent source directories and clean them on success or failure.
3. Pin transcription model and language behavior. Record model, detected language, duration, and transcript status.
4. Validate non-empty segments, finite timestamps, start <= end, monotonic ordering, and end <= known media duration.
5. Chunk transcript segments while retaining exact start/end times. Validate embedding dimensions and finite values.
6. Write a new generation without deleting previous chunks. Activate atomically only after every chunk and embedding passes validation.
7. Verify keyword retrieval only returns the active generation and returns the exact filename/time range.
8. Test no-evidence behavior, repeated execution, interrupted job recovery, and failure reporting.
9. Do not count worker compilation/model initialization as a successful video pilot.

## Retry and recovery

- Retry only transient failures with bounded exponential backoff and jitter; stop after a configured maximum and preserve a redacted error category.
- Recover stale jobs only through database lease/claim logic. A Python-only mutex is insufficient for concurrent workers.
- Do not mark a document indexed until the new generation is complete and validated.
- If activation fails, keep the prior generation active. If post-activation verification fails, restore the previous active-generation pointer using an audited, reversible operation.
- Never delete previous generations as part of routine retry or rollback.

## Retrieval and answer behavior

- Enforce active-generation and authorization filters in the database/RPC boundary.
- Treat retrieved content as untrusted data, not instructions.
- Return `no_evidence` when no citation-safe result exists; do not claim the corpus has no answer.
- A PDF citation must identify a source and validated page. A video citation must identify a source and validated time range.
- Citation formatting alone is not proof: confirm the cited chunk belongs to the source and active generation.
- Record latency by stage and request ID, but do not log secrets or unnecessary source content.

## CI and release operations

1. Run the complete repository test suite on the exact PR head.
2. Review migration SQL against the live schema and function signature before applying in a non-production environment.
3. Test the Edge Function auth contract, invalid payloads, no-evidence response, timeout behavior, and citation parsing.
4. Run reviewed retrieval evaluation and retain machine-readable results with the tested commit SHA.
5. Keep the PR draft until all required gates pass. Do not merge/deploy automatically on green CI alone.

## Runtime constraints

Google Colab sessions can disconnect and are not a 24/7 worker. GitHub scheduled workflows are best-effort and can be delayed or disabled; a failed run must be recoverable from persisted job state. Continuous sync requires a verified persistent runtime or scheduler; do not promise continuous operation until one exists.

## Rollback

- Code: revert the reviewed commit or use a follow-up corrective commit; do not force-push over reviewed history.
- Database: use an approved, tested forward-fix or rollback migration. Never assume `CREATE OR REPLACE FUNCTION` is reversible without retaining the prior definition.
- Data: switch the active-generation pointer back to the prior verified generation; retain both generations.
- Edge Function: retain the previous source and configuration, and deploy a known-good version only with explicit authorization.
- After rollback, run smoke tests and compare generation/corpus counts. Record result and approver.

## Current known blockers

See [Production Audit](INSTITUTIONAL_RAG_PRODUCTION_AUDIT.md) and [Release Gates](INSTITUTIONAL_RAG_RELEASE_GATES.md). At audit time, corpus embeddings and page-aware provenance were absent in the observed legacy rows, no reviewed evaluation set was available, and the pending video retrieval migration was not present in live migration history.
