from pathlib import Path

import pytest

import rag_pipeline


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "rag_pipeline.py"
MIGRATION = ROOT / "supabase" / "migrations" / "20261020055818_append_only_ingestion_generations.sql"


def test_worker_uses_versioned_stage_rpc_and_records_pdf_hash():
    worker = PIPELINE.read_text(encoding="utf-8")
    assert 'client.rpc("rag_worker_stage_document_generation"' in worker
    assert '"p_document_sha256": hashlib.sha256(pdf_bytes).hexdigest()' in worker
    assert 'client.rpc("rag_worker_replace_document_chunks"' not in worker
    assert 'activated_documents += int(result.get("activated_documents", 0))' in worker
    assert 'page_aware.get("active_generation") != generation_id' in worker
    assert 'indexed_doc.get("content_sha256") != document_sha256' in worker


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



def test_embed_document_requires_database_activation_gate(monkeypatch):
    monkeypatch.setattr(
        rag_pipeline,
        "encode_passages",
        lambda model, texts, batch_size: [[0.0] * rag_pipeline.MODEL_DIMS for _ in texts],
    )

    class FakeClient:
        def list_chunks(self, document_id):
            return [{
                "chunk_id": "11111111-1111-1111-1111-111111111111",
                "content_sha256": "a" * 64,
                "text_content": "small verified page chunk",
            }]

        def rpc(self, name, body):
            assert name == "rag_worker_store_embeddings"
            return {"stored": 1, "activated_documents": 0}

    with pytest.raises(RuntimeError, match="did not activate exactly one complete"):
        rag_pipeline.embed_document(FakeClient(), object(), "22222222-2222-2222-2222-222222222222", 8)


def test_embed_document_returns_only_after_generation_is_active(monkeypatch):
    monkeypatch.setattr(
        rag_pipeline,
        "encode_passages",
        lambda model, texts, batch_size: [[0.0] * rag_pipeline.MODEL_DIMS for _ in texts],
    )

    class FakeClient:
        def list_chunks(self, document_id):
            return [{
                "chunk_id": "11111111-1111-1111-1111-111111111111",
                "content_sha256": "a" * 64,
                "text_content": "small verified page chunk",
            }]

        def rpc(self, name, body):
            assert name == "rag_worker_store_embeddings"
            return {"stored": 1, "activated_documents": 1}

    stats = rag_pipeline.embed_document(FakeClient(), object(), "22222222-2222-2222-2222-222222222222", 8)
    assert stats == {
        "chunks_seen": 1,
        "embeddings_stored": 1,
        "activated_documents": 1,
    }
