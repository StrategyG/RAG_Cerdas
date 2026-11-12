from __future__ import annotations

import pytest

from scripts.embedding_integrity import (
    summarize_embedding_progress,
    validate_embedding_batch_size,
)


@pytest.mark.parametrize("invalid", [0, -1, True, False, 1.5, "32", None])
def test_batch_size_rejects_invalid_values(invalid):
    with pytest.raises(ValueError, match="positive integer"):
        validate_embedding_batch_size(invalid)


def test_batch_size_accepts_positive_integer():
    assert validate_embedding_batch_size(16) == 16


def test_missing_embedding_field_is_unknown_not_missing():
    records = [
        {"page_start": 1, "page_end": 1},
        {"page_start": 2, "page_end": 2, "embedding": None},
        {"page_start": 0, "page_end": 0, "embedding": [0.1]},
        {"page_start": True, "page_end": True},
    ]
    assert summarize_embedding_progress(records) == {
        "chunks": 4,
        "valid_page_mappings": 2,
        "invalid_page_mappings": 2,
        "embedding_present": 1,
        "embedding_missing": 1,
        "embedding_unknown": 2,
    }
