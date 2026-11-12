# IM19 scalable retrieval implementation note

**Status:** Implemented on a review branch; exact code commit a95363c passed CI (203 tests, 4.79s); the read-only benchmark harness is not yet run against staging.

## Change

The previous HybridRetriever selected every published chunk in the filtered corpus, transferred those rows into Python, and calculated BM25 in process. A hard limit of 20,000 chunks caused retrieval to abstain for larger eligible corpora and made Python memory usage proportional to corpus size.

The new implementation:

1. Uses a PostgreSQL GIN index over to_tsvector('pg_catalog.simple', text_content) for lexical candidate retrieval.
2. Uses the existing pgvector HNSW cosine index for dense candidates.
3. Retrieves at most 50 lexical and 50 dense candidates from the database.
4. Combines ranked candidates using Reciprocal Rank Fusion (RRF).
5. Keeps graph expansion limited to reviewed relationships.
6. Runs query embedding before opening the database transaction so CPU inference does not hold a database connection.
7. Keeps citation validation and the NOT_EXTERNALLY_VERIFIED status unchanged.

The lexical score is PostgreSQL ts_rank_cd; it is not BM25. The pure-Python bm25() helper remains only for small offline reference tests and is not used by the production retrieval path.

## Scale boundary

This removes the full-corpus Python scan, but it does not certify 5-million-unit capacity. The GIN/HNSW indexes, query plans, update rate, memory, disk, and p95 latency still require representative staging benchmarks. The current IM19 schema has no tenant_id columns or per-tenant RLS predicates; its broad worker policy is private-role scoped, not tenant isolation. The retriever is a private worker interface and must not be exposed as a multi-tenant public API. The canonical RUSA AI knowledge store is also unresolved: RusaAi main contains a separate optional tenant-scoped PostgreSQL/pgvector store. See [ADR-0001](ADR_0001_CANONICAL_KNOWLEDGE_STORE.md); do not dual-write or cross-read until a decision and contract are approved.

The IM19 schema is private and migrations are never applied by worker startup. The new migration is additive. Apply it only to an approved, backup-restored staging database after reviewing the target schema. For a populated production-sized index, assess index build locking and use the platform's approved online-index procedure rather than blindly applying DDL during service hours.

## RUSA AI corpus target correction

The RUSA AI Agent & Worker 5M Hybrid Corpus Expansion Plan v1.0 defines the 5,000,000 target as distinct, source-grounded, deduplicated, reviewed, permission-scoped knowledge units. It is not a count of raw chunks, repeated passages, prompts, embeddings, database rows, or vector points.

Keep these milestones separate:

- 50,000: initial production corpus target.
- 5,000,000: Agent/Worker knowledge-unit expansion target.
- 1,000,000,000: separate global platform-capacity objective.

Report raw candidates, unique candidates, reviewed units, approved units, embedded units, indexed units, and production-published units separately. The current Dropbox snapshot in the expansion plan is a raw candidate ledger, not an approved or indexed corpus.

## RUSA CPU-first alignment

- Start prose chunking at the RusaAi architecture baseline of 400–600 tokens.
- Evaluate 50–80 token overlap, applying it only where adjacent context is needed.
- Start retrieval with 3–6 chunks; expand only when evidence is insufficient.
- Respect the 8K context budget and dynamic Context Manager allocation.
- Keep ingestion, embedding, and indexing bounded and asynchronous so background work does not starve the shared CPU inference runtime.
- Do not load the full corpus or all embeddings into worker RAM.

The read-only benchmark harness is available at [IM19_BENCHMARK_GUIDE.md](IM19_BENCHMARK_GUIDE.md). It reports planner estimates, GIN/HNSW plan selection, buffer use, and p50/p95 database latency without changing data. It has not yet been run against a representative staging corpus.

## Validation still required

- Disposable PostgreSQL/pgvector migration and retrieval integration tests.
- EXPLAIN (ANALYZE, BUFFERS) against representative corpus sizes and tenant/project filters.
- 100K, 500K, 1M, and 5M capacity runs.
- Recall@5, MRR@10, citation accuracy, and abstention on human-reviewed qrels.
- CPU/RAM/disk/queue metrics on the approved deployment profile.
