from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.video_rag_worker import (
    EMBEDDING_MODEL,
    prepare_passages,
    split_segments,
    validate_embedding_vectors,
)


def _word(text: str, start: float, end: float):
    return SimpleNamespace(word=text, start=start, end=end)


def test_video_chunks_use_word_timestamps_and_overlap_without_gaps():
    items = [_word(f"w{i}", float(i), float(i) + 0.4) for i in range(45)]
    segment = SimpleNamespace(start=0.0, end=45.0, text=" ".join(w.word for w in items), words=items)

    chunks = split_segments([segment], max_words=20, overlap_words=5)

    assert [chunk["word_count"] for chunk in chunks] == [20, 20, 15]
    assert chunks[0]["text"].split()[-5:] == chunks[1]["text"].split()[:5]
    assert chunks[1]["text"].split()[-5:] == chunks[2]["text"].split()[:5]
    assert chunks[0]["start_seconds"] == 0.0
    assert chunks[0]["end_seconds"] == 19.4
    assert chunks[1]["start_seconds"] == 15.0
    assert all(chunk["timestamp_precision"] == "word" for chunk in chunks)
    assert all(chunk["end_seconds"] >= chunk["start_seconds"] for chunk in chunks)


def test_segment_timestamp_fallback_is_explicitly_marked():
    segment = SimpleNamespace(
        start=12.25,
        end=18.75,
        text=" ".join(f"spoken{i}" for i in range(25)),
    )

    chunks = split_segments([segment], max_words=20, overlap_words=5)

    assert len(chunks) == 2
    assert all(chunk["timestamp_precision"] == "segment" for chunk in chunks)
    assert all(chunk["start_seconds"] == 12.25 for chunk in chunks)
    assert all(chunk["end_seconds"] == 18.75 for chunk in chunks)


def test_e5_passage_prefix_is_applied_to_each_transcript_chunk():
    chunks = [{"text": "Membeli saham membutuhkan analisis."}, {"text": "Kelola risiko sebelum transaksi."}]

    assert EMBEDDING_MODEL == "intfloat/multilingual-e5-small"
    assert prepare_passages(chunks) == [
        "passage: Membeli saham membutuhkan analisis.",
        "passage: Kelola risiko sebelum transaksi.",
    ]


def test_embedding_validation_rejects_wrong_count_dimensions_and_nonfinite_values():
    valid_vector = [1.0] + [0.0] * 383
    assert validate_embedding_vectors([valid_vector], 1) == [valid_vector]

    with pytest.raises(ValueError, match="Expected 2"):
        validate_embedding_vectors([valid_vector], 2)
    with pytest.raises(ValueError, match="exactly 384"):
        validate_embedding_vectors([[1.0, 0.0]], 1)
    with pytest.raises(ValueError, match="non-finite"):
        validate_embedding_vectors([[float("nan")] + [0.0] * 383], 1)
    with pytest.raises(ValueError, match="not normalized"):
        validate_embedding_vectors([[0.0] * 384], 1)


def test_video_retrieval_migration_filters_active_generation_and_uses_e5():
    migration = Path(
        "supabase/migrations/20261023200123_video_rag_model_alignment.sql"
    ).read_text(encoding="utf-8")

    assert "d.metadata->'video_rag'->>'active_generation'" in migration
    assert "c.metadata->>'video_generation'" in migration
    assert "intfloat/multilingual-e5-small" in migration
    assert "c.metadata->>'start_timestamp'" in migration
    assert "c.metadata->>'end_timestamp'" in migration
    assert "c.page_start IS NOT NULL" in migration
    assert "c.page_end = c.page_start" in migration



def test_video_reingestion_is_append_only_and_generation_metadata_is_unambiguous():
    worker = Path("scripts/video_rag_worker.py").read_text(encoding="utf-8")

    assert "DELETE FROM rag.chunks" not in worker
    assert '"video_generation": generation' in worker
    assert '"previous_generations_retained": True' in worker
    assert '"chunk_count": len(chunks)' in worker
    assert '"generation_count"' not in worker
