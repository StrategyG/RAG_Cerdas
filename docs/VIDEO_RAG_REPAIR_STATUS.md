# Institutional RAG — Video Repair and Production Gate

**Date:** 2026-10-24  
**Branch:** `fix/video-rag-safe-generation`  
**Pull request:** #9 (draft)  
**Decision:** **NO-GO for production; pilot only after remaining gates pass**

## What changed in this branch

- Video worker defaults to `intfloat/multilingual-e5-small` and uses the E5 `passage:` prefix to match the 384-dimensional database vector contract.
- Embedding shape and finite values are checked before database writes.
- Video chunk replacement was changed to append-only generations; existing chunks are retained for audit/rollback.
- Each video chunk stores start/end seconds and timestamps.
- A migration updates keyword retrieval to select only the active video generation and emit a timestamp marker for citation.
- The Edge Function now accepts either a valid single-page PDF citation or a well-formed video timestamp citation; it drops results that have neither.
- Optional worker dependencies and regression tests were added; CI compiles the worker.

## Evidence and limitations

- GitHub Actions completed successfully for an earlier commit in this PR. Later commits added database/Edge Function timestamp-citation changes; **their exact latest CI result must be checked before merge**.
- The SQL migration is committed to the branch but **has not been applied to Supabase**.
- The Edge Function code is committed but **has not been deployed**.
- No Dropbox video was downloaded or transcribed in this repair run; no live ingestion or database writes were performed.
- The worker expects Dropbox source records in `rag.documents` to have `metadata.dropbox_id` and a usable video MIME type or video filename. A pilot must verify this against actual inventory.
- Existing live database audit showed 383 legacy documents (352 discovered, 31 failed, 0 indexed), 25,343 legacy chunks with no embeddings and no page mappings, 300 institutional source documents (298 discovered, 2 chunked, 0 indexed), 5 institutional chunks with no embeddings, and 0 evaluation cases/results. These counts must be rechecked before making release decisions.
- Retrieval is still keyword-based in the current ChatGPT Edge Function. Semantic retrieval, hybrid ranking, reranking, OCR for scanned PDFs, video quality checks, and a reviewed gold evaluation set are not established by this patch.
- Existing rows are not automatically repaired by merging this code. Backfill/re-ingestion requires a separate, controlled plan after the pilot passes.

## Required release gates

1. **CI:** latest PR head has successful workflow and regression tests.
2. **Schema:** review migration and verify deployed function signatures, grants, indexes, and triggers before applying it.
3. **Secrets:** store database and Dropbox credentials in authorized secret storage; never commit or print them.
4. **PDF pilot:** process one permitted PDF; verify extracted page numbers, 384-dimensional finite vectors, active generation, exact page citations, and retrieval results.
5. **Video pilot:** process one permitted video; verify transcript timestamps, active generation, timestamp citation output, and search results.
6. **Evaluation:** create at least 30 human-reviewed questions with evidence labels; measure Recall@k, MRR/nDCG, citation accuracy, and abstention on no-evidence questions.
7. **Operations/security:** verify retry/recovery, idempotency, backup/restore, RLS and service-role boundaries, logs without secrets, and rollback behavior.
8. **Release:** deploy migration and Edge Function only after explicit review; no bulk indexing until pilot and evaluation pass.

**Rule:** Keep the PR in draft until the latest CI is green and schema review is complete. Do not merge or label the system production-ready solely because the Python tests pass.
