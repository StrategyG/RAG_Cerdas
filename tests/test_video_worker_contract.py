from pathlib import Path


def test_video_worker_uses_shared_multilingual_embedding_model():
    source = Path("scripts/video_rag_worker.py").read_text(encoding="utf-8")
    assert 'intfloat/multilingual-e5-small' in source
    assert '"passage: " + chunk["text"]' in source
    assert 'vectors.shape != (len(chunks), 384)' in source


def test_video_worker_never_deletes_previous_chunks():
    source = Path("scripts/video_rag_worker.py").read_text(encoding="utf-8")
    assert "DELETE FROM rag.chunks" not in source
    assert "Append a new generation" in source
    assert '"video_generation": generation_id' in source
    assert '"active_generation": generation_id' in source


def test_video_worker_keeps_timestamp_citations():
    source = Path("scripts/video_rag_worker.py").read_text(encoding="utf-8")
    assert '"start_seconds": chunk["start_seconds"]' in source
    assert '"end_seconds": chunk["end_seconds"]' in source
    assert '"start_timestamp": _timestamp(chunk["start_seconds"])' in source
    assert '"end_timestamp": _timestamp(chunk["end_seconds"])' in source



def test_video_search_has_timestamp_citation_contract():
    edge = Path("supabase/functions/institutional-rag-search/index.ts").read_text(encoding="utf-8")
    migration = Path("supabase/migrations/20261024090000_video_timestamp_keyword_retrieval.sql").read_text(encoding="utf-8")
    assert 'citation_type: isVideoCitation ? "video_timestamp" : "pdf_page"' in edge
    assert 'start_timestamp: isVideoCitation ? videoMatch![1] : null' in edge
    assert "'video_rag'->>'active_generation'" in migration
    assert "c.metadata->>'video_generation'" in migration
    assert "start_timestamp" in migration and "end_timestamp" in migration
