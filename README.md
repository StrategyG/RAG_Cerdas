# IM19 — Intelligent Mind 19

Institutional RAG and Autonomous Knowledge Intelligence pilot. **Not production-ready.**

The new `im19` package supports incremental read-only Dropbox discovery, versioned PDF/EPUB processing, selective PDF OCR, structured knowledge extraction, five logical local-AI review roles, a private PostgreSQL/pgvector schema, fenced worker jobs and citation-safe hybrid retrieval. Publication remains under separate human approval while quality/risk benchmarks are uncalibrated. The legacy `rag_pipeline.py` path remains available.

Start with the [current audit](docs/IM19_AUDIT_20261025.md), [validation/readiness report](docs/IM19_VALIDATION_REPORT.md), [architecture](docs/IM19_ARCHITECTURE.md), [security report](docs/IM19_SECURITY_REPORT.md), [operational runbook](docs/IM19_RUNBOOK.md), and [retrieval evaluation evidence contract](docs/RETRIEVAL_EVALUATION_EVIDENCE_CONTRACT.md), and [Supabase live-schema reconciliation](docs/SUPABASE_LIVE_SCHEMA_RECONCILIATION_20261105.md).

## Retrieval evaluation safeguards

Retrieval metrics are calculated only for cases marked `reviewed` with a consistent human-review evidence envelope. Unreviewed labels are withheld and duplicate retrieved chunk IDs are removed before scoring. The evaluation report records the dataset SHA-256.

The evidence envelope is a structural validation, not authentication. Production evaluation must resolve reviewers against the authoritative reviewer registry, persist an immutable review record, and bind the reviewed labels to exact corpus and dataset versions. The current evaluation cases are unlabeled; no corpus-quality score is claimed. See the [evidence contract](docs/RETRIEVAL_EVALUATION_EVIDENCE_CONTRACT.md).

```bash
python -m pip install -r requirements-test.txt
python -m pytest -q --strict-config --strict-markers tests
# Local models/Tesseract and a reviewed staging migration are separate prerequisites:
python -m pip install -r requirements-knowledge.txt
python -m im19.cli health
python -m im19.cli discover --connection-id APPROVED_STAGING_UUID --max-pages 1
python -m im19.cli pilot --document-id ONE_STAGING_DOCUMENT_UUID
```

Use secret-manager mounts or Colab Secrets; never put tokens into source or notebook cells. `notebooks/IM19_Knowledge_Intelligence_Pilot.ipynb` is an unexecuted pilot notebook. `deploy/compose.knowledge.yml` is a reviewable deployment example, not a deployed service. No migration is automatically applied; no original Dropbox document is modified. Colab runs only while its runtime remains active.
