# Institutional RAG on GitHub Codespaces

The branch contains the page-aware ingestion worker, retrieval evaluator, regression tests, and Python 3.11 Codespaces configuration. Ingestion is **not** run automatically.

## 1. Open the Codespace

Open [this branch in GitHub](https://github.com/StrategyG/RAG_Cerdas/tree/codespaces-institutional-rag), then choose **Code → Codespaces → Create codespace**. On Android, use the browser's desktop-site mode if needed.

## 2. Configure credentials as Codespaces Secrets

In repository **Settings → Secrets and variables → Codespaces**, add:
- `SUPABASE_URL` = `https://uktauwysjkseqrnbjwzy.supabase.co`
- `SUPABASE_SERVICE_ROLE_KEY` = the server-only key from Supabase Dashboard → Project Settings → API Keys
- Optional `DROPBOX_ACCESS_TOKEN` with the Dropbox content-read scope needed to download source PDFs.

Restart the Codespace after changing secrets. Never commit real credentials or place the service-role key in browser code. The bootstrap intentionally does not copy `.env.example` into `.env`, because its key is a placeholder.

## 3. Verify the environment before touching the database

The devcontainer installs `requirements.txt` automatically. Run:

```bash
source .venv/bin/activate
python scripts/preflight.py
python -m compileall rag_pipeline.py eval_retrieval.py scripts/preflight.py
python -m pytest -q --strict-config --strict-markers tests
python rag_pipeline.py list
python rag_pipeline.py ingest --dry-run --status discovered --limit 1
```

The preflight checks that required values are present without printing them. The list operation is read-only. The dry-run does not enqueue jobs or write document/chunk data. **When Dropbox is configured, dry-run does not verify each remote path/token; it only marks Dropbox as a potential source.** A real one-document pilot is needed to prove Dropbox access.

## 4. Run a one-document pilot

Only after the dry-run output looks correct, process one discovered document:

```bash
python rag_pipeline.py ingest --status discovered --limit 1
```

The default selection is incremental (status `discovered`, limit 1) to avoid reprocessing the entire corpus by mistake. The worker creates page-bounded chunks and 384-dimensional `intfloat/multilingual-e5-small` embeddings, then records success only when all chunks satisfy page and embedding checks. CPU processing may be slow and the first run downloads model weights.

Inspect the JSON output and verify Supabase counts/status before continuing. If the pilot succeeds, process another batch using `--limit 1`. Only after the pipeline is proven should you expand the selection. To process all documents of a specific status intentionally, specify that status and `--limit 0`; do not start with an entire-corpus run.

If no local PDF exists, configure a Dropbox token with the necessary read access or add source PDFs under `data/pdfs/`. PDFs, model weights, `.env`, and evaluation outputs must not be committed.

## 5. Evaluate retrieval

After real page-aware ingestion and embeddings exist:

```bash
python eval_retrieval.py --cases eval_cases.json --k 5
```

The pilot evaluation cases contain questions and expected evidence but no human-reviewed gold chunk IDs. Consequently, ranking results can be inspected but precision, recall, MRR, and nDCG are not reported until reviewers label the new chunk IDs in `relevant_chunk_ids`. Page-citation accuracy also requires comparing returned page numbers to the original PDFs.

## 6. CI behavior and limits

GitHub Actions now fails if required pipeline/evaluation/test files are missing. It compiles required Python modules, runs tests with lightweight dependencies, and validates the evaluation-case schema. CI validates local code, **not** live Supabase credentials, Dropbox access, model download, or end-to-end ingestion.

The actual repository branch and cloud database state should be treated separately: a successful CI run is not proof that Codespaces has started, or that the corpus has been re-ingested.
