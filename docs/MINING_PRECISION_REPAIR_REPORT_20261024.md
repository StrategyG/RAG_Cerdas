# Institutional RAG mining precision repair report — 2026-10-24

## Decision

**MODIFY / NOT READY FOR MASS INGESTION.** Source catalog coverage was corrected for six missing MP4s and the pipeline code was hardened, but full content mining has not run and quality is not yet measured. Do not mark production-ready until the migration, tests, ingestion pilot, retrieval, and citations are independently verified.

## Live inventory verification

Full recursive Dropbox listing completed in two pages:

- 401 entries total.
- 360 PDF files.
- 23 MP4 videos.
- 18 folders.

Supabase `rag.documents` initially had 360 PDF rows and 17 video rows. Six missing MP4 catalog rows were inserted additively (all received fresh UUIDs and status `discovered`). Read-only verification after insertion returned 23 video rows, 23 `discovered`, 0 `indexed`, 0 `failed`; there are still 0 video chunks and 0 video embeddings. No video transcription or PDF ingestion ran as part of catalog repair.

Six newly registered videos:
- `04 Analisa Teknikal.mp4`
- `03 Siapa cocok investasi saham.mp4`
- `01 Introduction (1).mp4`
- `05 Mengenal Instrumen Investasi Defensive vs Growth.mp4`
- `01 Introduction (2).mp4`
- `02 Dana Darurat Gausah Bingung!.mp4`

PDF catalog reconciliation:
- 360 PDF records in Supabase, 360 PDF paths in Dropbox.
- No registered PDF source-size mismatch was observed.
- `/Institutional_RAG/01_RAW_SOURCES/Lesson 4 How emotions can affect your trading results.pdf` exists in Dropbox but is an exact duplicate of the root source documented by the earlier inventory; it remains intentionally unregistered to avoid duplicate ingestion.
- `/akses 1000+.pdf` remains as a stale `failed` catalog record because it was not found in Dropbox. It was not deleted or overwritten.
- The 360 existing PDF catalog rows had no `content_sha256`; source integrity has not yet been verified by downloading and hashing every PDF.

## Live Supabase data state

- Current live state: 360 PDF rows; 329 `discovered`, 31 `failed`, 0 `processing`, and 0 `indexed`.
- Audit logs record 103 `orphan_processing_recovered` events at `2026-10-23 19:59:01 UTC`; those rows were returned to `discovered` before the new retrieval migration was applied. This reset was not performed by the retrieval migration.
- 23 MP4 rows after catalog reconciliation: 23 `discovered`, 0 `indexed`.
- Read-only chunk audit: 25,343 legacy rows; 0 embeddings, 0 page-mapped chunks, 0 `qdrant_point_id` values, and 0 `embedding_model` values.
- `rag.ingest_jobs` currently has 0 rows.

## Code changes on `codespaces-institutional-rag`

- Video embeddings use the same pinned `intfloat/multilingual-e5-small` model and `passage:` prefix as PDF passages, matching the current query encoder.
- Video chunks use overlapping timestamped word groups and explicitly record word-level versus segment-level timestamp precision.
- Video retries append a new generation; they no longer delete all old chunks. A new generation is activated only after transcription, source-size/hash checks, embedding validation, and insertion succeed.
- Embeddings are rejected for wrong count/dimensions, non-finite values, non-normalized vectors, and chunks that exceed the encoder's token limit.
- PDF extraction now refuses to stage a partial generation when a page appears to be a large scanned image with too little selectable text; this requires OCR or an explicit parse-failure resolution.
- A new SQL migration updates keyword/semantic retrieval to use active video generations, filter semantic results to the common E5 model, include video time labels in evidence text, and exclude PDF chunks that lack valid single-page citations.
- Unit tests and CI checks were added for these contracts.

## Explicitly not yet verified

- The migration `20261023200123_video_rag_model_alignment.sql` has been applied to the live Supabase project and verified in migration history. Read-only function checks confirm active-video-generation filters, E5-model filtering for semantic retrieval, and single-page mapping checks for PDF retrieval.
- GitHub Actions returned no usable run/status evidence for these latest changes; do not claim the tests passed.
- No live Codespaces terminal execution was performed.
- No complete PDF download/hash audit, OCR pass, PDF mining, video transcription, embedding, or semantic retrieval test ran.
- Gold evaluation cases still require human-reviewed relevance labels before Recall@k, MRR, or nDCG can be measured honestly.

## Release gates

1. Run the branch unit tests in Codespaces/GitHub Actions and fix failures.
2. Review/apply the retrieval migration through the repository's normal migration process; verify the wrapper functions still work and keep the intended service-role permissions.
3. Run PDF source audit and inspect the 103 orphaned/stale `processing` statuses before requeueing any jobs.
4. Run one PDF dry-run and a one-PDF ingestion pilot; verify source SHA-256, page count, active generation, all embeddings, and one-page chunk maps.
5. Run one MP4 pilot; verify downloaded size/hash, transcript against the original clip, E5 vector count, active generation, increasing timestamps, and title/timestamp citation.
6. Create a human-reviewed evaluation set across several PDFs/videos, including answerable, page-specific, timestamp-specific, conflicting, and unanswerable questions. Measure retrieval and citation quality before batch ingestion.

**Safety invariant:** original Dropbox sources and legacy database chunks remain untouched by this repair; stale catalog records are preserved for review.
