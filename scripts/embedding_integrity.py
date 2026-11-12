"""Conservative, read-only embedding generation recovery diagnostics.

Never reset document status or mutate chunks based on guesses. The caller can
inspect the result and decide whether a fresh ingestion is necessary.
"""
from __future__ import annotations

from typing import Any


def summarize_embedding_progress(chunks: list[dict[str, Any]]) -> dict[str, int]:
    """Count valid/invalid citation metadata and outstanding embedding work.

    Embedding presence is not inferred from a chunk ID or source hash. Missing
    embedding keys are treated as unknown rather than as verified absent.
    """
    summary = {
        "chunks": len(chunks),
        "valid_page_mappings": 0,
        "invalid_page_mappings": 0,
        "embedding_present": 0,
        "embedding_missing": 0,
        "embedding_unknown": 0,
    }
    for chunk in chunks:
        start, end = chunk.get("page_start"), chunk.get("page_end")
        if type(start) is int and start >= 1 and type(end) is int and end == start:
            summary["valid_page_mappings"] += 1
        else:
            summary["invalid_page_mappings"] += 1
        if "embedding" not in chunk:
            summary["embedding_unknown"] += 1
        elif chunk["embedding"] is None:
            summary["embedding_missing"] += 1
        else:
            summary["embedding_present"] += 1
    return summary


def validate_embedding_batch_size(batch_size: int) -> int:
    """Reject zero, negative, boolean and noninteger batch sizes explicitly."""
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("embedding batch_size must be a positive integer")
    return batch_size
