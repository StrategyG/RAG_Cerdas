# Institutional RAG on GitHub Codespaces

This branch configures a Python 3.11 Codespace for the page-aware RAG worker. Ingestion does not run automatically.

## 1. Open Codespaces
Open repository `StrategyG/RAG_Cerdas`, switch to branch `codespaces-institutional-rag`, then choose **Code → Codespaces → Create codespace**. On a phone, use the browser's desktop-site mode if needed.

## 2. Add secrets
In GitHub **Settings → Secrets and variables → Codespaces**, add:
- `SUPABASE_URL` = `https://uktauwysjkseqrnbjwzy.supabase.co`
- `SUPABASE_SERVICE_ROLE_KEY` = the server-only key from Supabase Dashboard → Project Settings → API Keys
- Optional `DROPBOX_ACCESS_TOKEN` if the worker needs Dropbox content-read access.

Never commit credentials or put a service-role key in browser code. Restart the Codespace after changing secrets.

## 3. Add the worker package
Upload `institutional_rag_pipeline_upgrade_20261018.zip` to the repository or Codespace file explorer. Then run in the terminal (adjust the ZIP path if needed):

```bash
unzip -o institutional_rag_pipeline_upgrade_20261018.zip
cp -a institutional_rag_pipeline/. .
rm -rf institutional_rag_pipeline
python -m pip install -r requirements.txt
```

Do not commit PDFs, model weights, `.env`, or evaluation outputs.

## 4. Validate before writes
```bash
source .venv/bin/activate
python scripts/preflight.py
python -m compileall rag_pipeline.py eval_retrieval.py
python -m pytest -q
python rag_pipeline.py list
python rag_pipeline.py ingest --dry-run
```
Review dry-run results; stop if the intended source PDFs are not found.

## 5. Run ingestion after reviewing dry-run
```bash
python rag_pipeline.py ingest --enqueue
```
CPU embedding may be slow; the first run downloads `intfloat/multilingual-e5-small`. Never mark documents indexed manually.

## 6. Evaluate
```bash
python eval_retrieval.py --cases eval_cases.json --k 5
```
Pilot cases currently lack reviewed gold chunk labels, so relevance metrics must remain unavailable until humans verify and label retrieved evidence. Citation accuracy requires original PDFs ingested with verified page boundaries.

## Current limitation
The Codespaces configuration is not proof of a successful end-to-end run. The existing Supabase corpus still needs real page-aware re-ingestion and embedding generation.