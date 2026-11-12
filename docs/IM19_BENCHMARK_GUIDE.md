# IM19 read-only retrieval benchmark guide

## Purpose

Use this harness to inspect the PostgreSQL access paths for the lexical GIN and vector HNSW candidate queries introduced in the indexed retrieval change.

It is a **read-only database benchmark**, not a production-capacity certificate. It does not evaluate embedding quality, answer quality, relevance, citations, tenant isolation, or end-to-end CPU throughput.

## Safety

- Run only against an explicitly approved disposable or staging database.
- The script requires the restricted im19_worker database role, rejects superuser/BYPASSRLS/approver roles, sets the session read-only, and marks every benchmark transaction READ ONLY.
- It requires sslmode=verify-full unless --allow-local-test is explicitly used for a loopback or Unix-socket disposable database.
- It does not apply migrations, change source records, create/drop indexes, claim jobs, or write excerpts to the report.
- It reports planner row estimates rather than running full-table COUNT(*) scans.
- Do not point it at production without a separate change approval, query-window approval, and resource review.

## Prerequisites

- Apply the reviewed IM19 schema and lexical-index migration to the approved staging database.
- Configure the mounted secret IM19_DATABASE_DSN.
- Set IM19_EMBEDDING_SHA256 to the exact approved E5 model tree hash used by the corpus.
- Use the same embedding model version and a representative normalized 384D query vector for the dense query.

## Run

Default mode uses a synthetic normalized unit vector. It is suitable for checking whether the database can plan and execute the HNSW access path, but it is not a relevance or quality test.

    python scripts/benchmark_im19_retrieval.py --query "retrieval benchmark" --warmup 3 --iterations 20 --output im19-retrieval-benchmark.json

For a representative query vector, provide a JSON file containing exactly 384 finite, normalized values:

    python scripts/benchmark_im19_retrieval.py --query "tenant scoped knowledge retrieval" --vector-json "$(cat query-vector-384.json)" --warmup 3 --iterations 50

The vector file is an operator-supplied local input. Do not commit private query vectors or source content to Git.

## Report interpretation

The report includes:

- PostgreSQL planner estimates for chunks, embeddings, knowledge units, and document versions.
- Table sizes and GIN/HNSW index definitions.
- EXPLAIN ANALYZE BUFFERS plan summaries for lexical and dense candidate queries.
- Actual p50/p95 database query latency after warm-up.
- Whether the expected GIN and HNSW indexes exist and which indexes the planner actually used.

If the planner selects a sequential scan, preserve the plan and staging statistics; do not force index use or change production planner settings merely to make the report look successful.

## Required capacity evidence

Repeat on representative datasets at 10K, 50K, 100K, 1M, and 5M stages, and record exact database version, hardware, corpus/index snapshot, model version, query set, iterations, and report SHA-256. Run a separate end-to-end benchmark for CPU embedding, queue wait, retrieval, reranking, context assembly, and answer generation.

The 5M target is distinct reviewed knowledge units, not a planner estimate of chunks or embedding rows. Do not infer a completed target from the table estimates.
