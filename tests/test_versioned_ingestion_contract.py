from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "rag_pipeline.py"
MIGRATION = ROOT / "supabase" / "migrations" / "20261020080000_append_only_ingestion_generations.sql"


def test_worker_uses_versioned_stage_rpc_and_records_pdf_hash():
    worker = PIPELINE.read_text(encoding="utf-8")
    assert 'client.rpc("rag_worker_stage_document_generation"' in worker
    assert '"p_document_sha256": hashlib.sha256(pdf_bytes).hexdigest()' in worker
    assert 'client.rpc("rag_worker_replace_document_chunks"' not in worker


def test_migration_is_append_only_and_retires_destructive_rpc():
    sql = MIGRATION.read_text(encoding="utf-8")
    normalized = sql.lower()
    assert "delete from rag.chunks" not in normalized
    assert "rag_worker_stage_document_generation" in normalized
    assert "drop function if exists public.rag_worker_replace_document_chunks(uuid, integer, jsonb)" in normalized
    assert "'previous_chunks_retained', true" in normalized
    assert "'pending_generation'" in normalized
    assert "'active_generation'" in normalized
    assert "content_sha256 = pg_catalog.lower" in normalized


def test_retrieval_queries_filter_to_active_generations_without_hiding_legacy():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE OR REPLACE FUNCTION rag.match_chunks_keyword" in sql
    assert "CREATE OR REPLACE FUNCTION rag.match_chunks_semantic" in sql
    assert "c.metadata->>'ingest_generation' = d.metadata->'page_aware_ingest'->>'active_generation'" in sql
    assert "AND c.metadata->>'ingest_generation' IS NULL" in sql
