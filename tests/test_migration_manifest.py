from pathlib import Path


MIGRATIONS_DIR = Path("supabase/migrations")

# This manifest is derived from the connected Supabase project's recorded
# supabase_migrations.schema_migrations history as of 2026-10-24.
APPLIED_MIGRATIONS = {
    "20261018104658_institutional_rag_core_schema.sql",
    "20261018142128_enable_pgvector_extension.sql",
    "20261018142529_add_embedding_metadata_columns.sql",
    "20261018142537_index_rag_foreign_key_columns.sql",
    "20261018142554_add_private_semantic_search_rpc.sql",
    "20261018142609_add_partial_hnsw_embedding_index.sql",
    "20261018143344_harden_private_rag_access_and_keyword_search.sql",
    "20261018143507_deny_direct_api_access_and_validate_chunk_metadata.sql",
    "20261018164423_page_aware_ingestion_embedding_worker.sql",
    "20261018164451_remove_duplicate_page_index.sql",
    "20261018164547_page_aware_worker_read_apis.sql",
    "20261018182702_claim_ingest_jobs_only.sql",
    "20261018183310_drop_duplicate_ingest_job_index.sql",
    "20261020055818_append_only_ingestion_generations.sql",
    "20261023160809_institutional_rag_foundation.sql",
    "20261023161150_institutional_rag_lexical_retrieval.sql",
    "20261023195626_citation_safe_retrieval_and_evaluation_index.sql",
    "20261023200123_video_rag_model_alignment.sql",
}

# Present locally but not recorded as applied in the connected project.
PENDING_REVIEW_MIGRATIONS = {
    "20261020130000_whatsapp_inbox.sql",
    "20261024090000_video_timestamp_keyword_retrieval.sql",
}


def test_all_recorded_applied_migrations_are_version_controlled():
    present = {p.name for p in MIGRATIONS_DIR.glob("*.sql")}
    assert APPLIED_MIGRATIONS <= present
    assert PENDING_REVIEW_MIGRATIONS <= present


def test_migration_versions_are_unique_and_no_unknown_files_are_silent():
    present = {p.name for p in MIGRATIONS_DIR.glob("*.sql")}
    expected = APPLIED_MIGRATIONS | PENDING_REVIEW_MIGRATIONS
    assert present == expected
    versions = [name.split("_", 1)[0] for name in present]
    assert len(versions) == len(set(versions)), "duplicate migration versions found"


def test_pending_rag_video_migration_is_after_recorded_history():
    version = "20261024090000_video_timestamp_keyword_retrieval.sql".split("_", 1)[0]
    latest_applied = max(name.split("_", 1)[0] for name in APPLIED_MIGRATIONS)
    assert version > latest_applied
