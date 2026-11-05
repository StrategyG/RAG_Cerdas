# Supabase live schema and migration reconciliation

**Observation date:** 2026-11-05  
**Environment:** Connected Supabase project; read-only inspection  
**Decision:** NO-GO for new production migrations until migration ownership and source history are reconciled

## Scope and evidence

The connected Supabase project reports PostgreSQL 17.11.0.003 and an active/healthy project state. Read-only catalog queries and the Supabase migration listing returned the following:

| Item | Observed result |
|---|---|
| Applied migration ledger | 74 versions |
| Tables in `public` | 0 |
| Tables in `institutional_rag` | 21 |
| Tables in `rag` | 4 |
| Tables in `im19` | 0 / schema not present in inspected schemas |
| Installed pgvector | 0.8.2 |
| Installed pgcrypto | 1.3 |
| Installed pg_stat_statements | 1.11 |

The `RAG_Cerdas/main` repository currently contains 5 files in `supabase/migrations/`. The checked-in migration `20261025010000_im19_knowledge_intelligence.sql` creates a private `im19` schema. The live database inspection did not find that schema; instead it found `institutional_rag` and `rag`.

This is a migration-source reconciliation blocker. The 69 ledger entries not present in this repository's current migration directory may be owned by other repositories, may have been applied from another source, or may reflect missing repository history. This report does not assume which explanation is correct.

## Access-control observations

- All 21 tables in `institutional_rag` had RLS enabled and no table-specific policies.
- The inspected schema ACL did not grant schema USAGE to `anon` or `authenticated`.
- The inspected table ACLs did not grant SELECT to `anon` or `authenticated`; table access was assigned to `postgres` and/or `service_role`.
- The four tables in `rag` had RLS enabled and a `deny_api_roles` policy for `anon` and `authenticated`; schema usage and table SELECT were also not granted to those roles.
- The security advisor's `rls_enabled_no_policy` informational findings for `institutional_rag` therefore do not, by themselves, establish public table access.

Do not add broad RLS policies simply to silence the informational advisor. Preserve the service-only boundary unless an approved client-facing access requirement is defined. Any future policy must be accompanied by role grants, positive tests, negative cross-tenant tests, and review of service-role bypass behavior.

## Data-volume observations

PostgreSQL `pg_stat_user_tables.n_live_tup` is an estimate, not an exact count. The observed estimates included approximately 383 rows in `rag.documents`, 26,186 in `rag.chunks`, and 1,071 in `rag.audit_events`. The `institutional_rag` schema included approximately 434 source documents and 1,109 document chunks. These are catalog estimates and must not be used as a migration completeness checksum.

## Required reconciliation before the next migration

1. Export the complete 74-version migration ledger with timestamps and source ownership.
2. Inventory migration files and release commits from every repository that has ever modified this Supabase project.
3. Map each applied version to exactly one source repository, commit SHA, and deployment record.
4. Compare the checked-in DDL with actual live DDL for `institutional_rag`, `rag`, and any schema referenced by applications.
5. Identify intentional legacy schemas, private service schemas, views, functions/RPCs, triggers, grants, RLS policies, and extension versions.
6. Create a canonical migration ownership map and a reproducible clean-database bootstrap path.
7. Rehearse any reconciliation on an isolated database restored from a verified backup.
8. Only then approve an additive migration or a separately reviewed deprecation plan.

## Explicit prohibitions

- Do not apply `20261025010000_im19_knowledge_intelligence.sql` to the connected live project merely because the schema is absent.
- Do not recreate, rename, move, truncate, or drop live schemas or tables to match one repository.
- Do not mark a migration as reconciled based only on migration filenames or row-count estimates.
- Do not treat the 74-version ledger as evidence that the current repository alone owns all 74 changes.
- Do not cut over from Supabase to a PostgreSQL VM until schema, data, authorization, backup/restore, performance, and rollback gates pass.

**Current disposition:** catalog inspection only. No database changes, migrations, backup, restore, or cutover were performed during this inspection.


## Production-readiness view snapshot

A read-only query of the live `institutional_rag.production_readiness_v1` and `institutional_rag.system_status` views returned this snapshot on 2026-11-05:

| Signal | Observed | Interpretation |
|---|---:|---|
| Registered source documents | 434 | Registered is not indexed |
| Indexed source documents | 0 | Source catalog/indexing gate fails |
| Document chunks | 1,109 | Chunks exist but are not proof of retrievable vectors |
| Embedded chunks | 0 | No embedded corpus was observed in this view |
| Ingestion runs | 4 | Run count alone does not prove completion |
| Active evaluation cases | 34 | Active cases are not necessarily independent or human-curated |
| Evaluation result rows | 38 | Rows alone do not satisfy independent evaluation acceptance |
| Verified human reviewers | 0 | No active verified reviewer identities were observed |
| Auth users | 0 | No auth user rows were observed by the readiness query |
| Independent human-curated cases | 0 | Minimum release threshold is 50 |
| Independently scored cases | 0 | Minimum release threshold is 50 |
| AI triage candidates | 528 | The advisory triage count gate passes |
| Embedding jobs aligned with source/review state | 293 / 293 | Alignment gate passes; completion and vectors remain separate |
| Approved knowledge excerpts | 0 | No approved/published cited excerpt |
| Approved embedding model artifacts | 0 | Model attestation gate fails |
| Completed staging embeddings with verified model | 0 | Minimum release threshold is 30 |

The database view reports 9 gates: 2 pass (`AI_TRIAGE_RECORDED`, `HOLD_NOT_SILENTLY_INDEXED`) and 7 fail. Failed gates include approved knowledge, embedding model attestation, independent evaluation set/run, reviewer identity, source catalog indexing, and staging embedding validation.

These numbers are a snapshot from the database's own readiness views, not a full audit of external object storage or a test of retrieval relevance. Counts and readiness rules can change as records are added or view definitions are updated. Re-run the same query and record its transaction timestamp and code/migration version before each release decision.

**Release conclusion from this snapshot: NO-GO.** Do not manufacture reviewers, labels, embeddings, indexed status, or approvals to satisfy the view. The missing evidence must be produced through the real ingestion, model attestation, independent human review, and benchmark workflows.


## Correction: per-store live counts (2026-11-05)

A subsequent exact-count query against both stores clarified that the readiness snapshot above is scoped to `institutional_rag`, not the entire Supabase project. Do not interpret its zero embedding count as a project-wide count.

| Store | Documents | Document/chunk rows | Rows with vectors | Document status |
|---|---:|---:|---:|---|
| `institutional_rag` | 434 | 1,109 | 0 | 432 discovered; 2 chunked |
| `rag` | 383 | 26,186 | 682 | 328 discovered; 55 failed |

The legacy `rag` store has 682 chunks with non-null vectors, but this count alone does not prove model provenance, freshness, retrieval availability, or acceptable relevance. The institutional knowledge pipeline has no embedded chunks in its own canonical tables and remains blocked by its approval and evaluation gates.

This distinction is important: two schemas have different lifecycle models and must not be combined into one readiness number. Before migration or deprecation, define which store is authoritative for each corpus, map document identity and content hashes, verify object-store sources, and test retrieval against each corpus separately. Do not copy or delete records merely to make the counts match.


## Legacy `rag` integrity detail (exact live query, 2026-11-05)

A further read-only integrity query measured the legacy `rag` corpus separately:

- 383 documents: 328 `discovered`, 55 `failed`, 0 `indexed`.
- 26,186 chunks; 682 have non-null embeddings and all 682 also have a non-empty `embedding_model`.
- 835 chunks have a valid page range, including 835 single-page mappings.
- 0 chunks have a `qdrant_point_id`.
- 1 ingest job is recorded as `succeeded`.

The five most recently updated failed records inspected carry the error `ORPHANED_PROCESSING_STATE`: no active ingestion lease/job for over 48 hours. Existing chunks are preserved. This is evidence of a prior stuck-worker recovery classification, not proof that the documents are safe to reprocess. Do not reset or requeue them in bulk. Reconcile each document's source hash, current active chunk generation, lease history, and source bytes before a one-document retry.

**Interpretation:** the legacy corpus has some embedded chunks, but its document lifecycle is not complete and its 682 vectors cannot be assumed to represent a complete, retrievable corpus. A missing `qdrant_point_id` is not itself a failure if the approved retrieval path uses pgvector; verify the actual RPC and vector index path before requiring external Qdrant identifiers.

The `institutional_rag` store remains distinct: 434 source documents (432 discovered, 2 chunked), 1,109 chunks, 0 embedded chunks, and 486 pending plus 183 `needs_more_evidence` knowledge candidates. The two stores require separate release gates and a documented authority map.
