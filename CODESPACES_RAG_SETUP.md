# Institutional RAG on GitHub Codespaces

This branch contains the page-aware PDF ingestion worker, retrieval evaluator, regression tests, Codespaces environment, and a read-only connectivity preflight. The worker never ingests automatically at Codespace creation.

## 1. Create a Codespace from the right branch

Open [the branch](https://github.com/StrategyG/RAG_Cerdas/tree/codespaces-institutional-rag), then choose **Code → Codespaces → Create codespace**. On Android, use desktop-site mode if GitHub hides the Code menu. Use the current branch; do not start from `main` unless these changes have been merged there.

## 2. Provide secrets securely

The devcontainer declares recommended secret names so GitHub can prompt for values during Codespace creation. If a Codespace already exists, configure the secrets in GitHub **Settings → Secrets and variables → Codespaces**, then restart the Codespace.

Required:
- `SUPABASE_URL` = `https://uktauwysjkseqrnbjwzy.supabase.co`
- `SUPABASE_SERVICE_ROLE_KEY` = server-side **Secret key** (`sb_secret_...`) from Supabase Dashboard → Settings → API Keys. A legacy `service_role` JWT also works during migration, but do not use the `anon` or publishable key.

Optional for Dropbox-backed source retrieval:
- `DROPBOX_ACCESS_TOKEN` = Dropbox token with the content-read permission needed to download PDFs.
- `DROPBOX_PREFLIGHT_PATH` = optional Dropbox path to a small accessible PDF. Defaults to `/Lesson 4 How emotions can affect your trading results.pdf`.

Supabase's new `sb_secret_...` key is not a JWT: this worker sends it in the `apikey` header only. Legacy `service_role` JWTs are sent in both `apikey` and `Authorization: Bearer`. Never commit secret values, paste them into ChatGPT, or put a server key in browser code. See [Supabase API key guidance](https://supabase.com/docs/guides/getting-started/api-keys) and [migration guidance](https://supabase.com/docs/guides/getting-started/migrating-to-new-api-keys). The setup script intentionally does not copy placeholder credentials from `.env.example` into `.env`.

## 3. Verify dependencies and real connections

The devcontainer installs both runtime (`requirements.txt`) and test (`requirements-test.txt`) dependencies. In the terminal:

```bash
source .venv/bin/activate
python scripts/preflight.py
python -m compileall rag_pipeline.py eval_retrieval.py scripts/preflight.py
python -m pytest -q --strict-config --strict-markers tests
```

Preflight now makes a **read-only request** to `rag_worker_list_documents_page` using the actual Supabase URL/key. If Dropbox token is set, it downloads the configured preflight PDF and verifies its PDF signature. It prints only connection status—not secret values. An HTTP/auth/scope failure is a blocker, not a successful setup.

## 4. Verify the pilot document before writing

The known pilot document is:

- Name: `Lesson 4 How emotions can affect your trading results.pdf`
- Supabase document UUID: `041f30c6-5957-49c0-a29b-e3c29a4e1ab0`
- Dropbox path: `/Lesson 4 How emotions can affect your trading results.pdf`

Run the read-only list command and a dry-run against exactly that document:

```bash
python rag_pipeline.py list
python rag_pipeline.py ingest --document-id 041f30c6-5957-49c0-a29b-e3c29a4e1ab0 --status discovered --limit 1 --dry-run
```

Dry-run now attempts to retrieve the actual local/Dropbox bytes and verifies the PDF signature and SHA-256. It does not enqueue jobs or write chunks/embeddings. It must show exactly the intended document and `source_check: ok`. Dropbox-backed dry-run is a read operation but does download the selected PDF.

If the document status has changed from `discovered`, choose the matching status explicitly after checking `list`. Do not use `--status all --limit 0` for the initial pilot.

## 5. Run one-document ingestion

Only after the dry-run and preflight pass:

```bash
python rag_pipeline.py ingest --document-id 041f30c6-5957-49c0-a29b-e3c29a4e1ab0 --status discovered --limit 1
```

The worker splits extracted text within individual PDF pages, writes page-numbered chunks, generates normalized 384-dimensional `intfloat/multilingual-e5-small` embeddings, and updates the indexed state only when all chunks have embeddings and page mappings. The database RPC will reject stale content hashes or unmapped chunks.

The queue now has a dedicated ingest-only claim RPC and a partial unique index to avoid more than one active ingest job per document/type. The worker scopes claims to the selected document UUIDs; it will not accidentally claim other job types or unrelated documents. CPU embedding may be slow on first run because model weights must be downloaded.

Run the read-only SQL checks in [`supabase/verification/verify_ingestion_state.sql`](https://github.com/StrategyG/RAG_Cerdas/blob/codespaces-institutional-rag/supabase/verification/verify_ingestion_state.sql) and inspect the resulting document/chunk counts before processing another PDF. If a document fails, read its `ingest_error`; correct the source or token problem first. Retry only that document, with its actual current status.

## 6. Expand to the full corpus

Do this only after the one-document pilot is successful and Codespaces Secrets are verified. First audit every recoverable document's source metadata without downloading PDFs or writing to Supabase:

```bash
python rag_pipeline.py ingest --status all --limit 0 --audit-sources
```

This checks all documents that are not already `indexed` or `skipped`, including the existing `discovered`, `processing`, and `failed` records. For Dropbox, the token needs both metadata-read permission (for `files/get_metadata`) and content-read permission (for `files/download`). Any missing path, size mismatch, inaccessible file, or invalid local PDF signature is reported. Fix source issues and rerun the audit until `sources_failed: 0`; do not proceed while the audit has failures unless you intentionally accept a partial corpus.

Then start the complete recoverable-corpus run:

```bash
python rag_pipeline.py ingest --status all --limit 0 --continue-on-error
```

Safety/behavior:
- `--limit 0` explicitly selects all eligible documents; the normal default remains one document.
- `--status all` excludes `indexed` and `skipped` documents unless `--reprocess-indexed` is explicitly added. Do not add that flag for a normal first corpus run.
- The worker verifies source metadata and expected file size before enqueueing; each actual download is checked again for PDF signature and file size.
- Each document is page-split, written through the server-only RPC, embedded with the 384-dimensional multilingual E5 model, and only marked indexed when the database gate passes.
- `--continue-on-error` allows the worker to continue through other selected documents if one fails. The final process exits nonzero when any document fails, and each failure is printed; fix source/OCR/permission issues and rerun only the failed set after reviewing current statuses.
- This operation writes to Supabase and downloads the selected corpus from Dropbox. It can take a long time and consume Codespaces CPU, memory, network, and storage. Keep the Codespace running, do not close it while work is in progress, and do not start a second worker concurrently.

After completion, run the read-only checks in `supabase/verification/verify_ingestion_state.sql`. Check that indexed documents have complete page mappings and embeddings. Scanned/image-only PDFs will fail text extraction and need an OCR stage; do not mark them indexed manually.

## 7. Evaluate only with reviewed labels

```bash
python eval_retrieval.py --cases eval_cases.json --k 5
```

The three pilot questions have expected evidence notes but no manually reviewed gold chunk IDs. The evaluator inspects keyword and semantic results, but it must withhold P@5, Recall@5, MRR@5, and nDCG@5 until a reviewer labels the new chunk IDs under `relevant_chunk_ids`. Citation accuracy requires checking page numbers against the original PDFs.

## 8. What CI proves—and does not prove

GitHub Actions fails if required source/test files are absent. It compiles the worker and evaluator, runs regression tests, and validates evaluation cases. This is code validation only; it does not use production secrets, start a Codespace, download the embedding model, or execute real ingestion.

A production-ready claim requires the one-document Codespaces pilot, successful Supabase state checks, retrieval quality labels, and original-PDF citation checks.
