"""Only explicitly human-reviewed records contribute to knowledge quality metrics."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def has_human_review_attestation(record: dict[str, Any]) -> bool:
    """Validate the required review-evidence envelope.

    This checks structure and consistency only. A production evaluator must still
    resolve reviewer_id against the authoritative human reviewer registry and
    verify the approval/audit record before treating this envelope as trusted.
    """
    if not isinstance(record, dict):
        return False

    attestation = record.get("review_attestation")
    reviewer_id = record.get("reviewer_id")
    if (
        not isinstance(attestation, dict)
        or not isinstance(reviewer_id, str)
        or not reviewer_id.strip()
        or reviewer_id != reviewer_id.strip()
    ):
        return False
    if attestation.get("reviewer_id") != reviewer_id:
        return False
    if attestation.get("reviewer_type") != "human":
        return False

    rubric_version = attestation.get("rubric_version")
    reviewed_at = attestation.get("reviewed_at")
    if not isinstance(rubric_version, str) or not rubric_version.strip():
        return False
    if not isinstance(reviewed_at, str) or not reviewed_at.strip():
        return False

    try:
        timestamp = datetime.fromisoformat(reviewed_at.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return timestamp.tzinfo is not None and timestamp.utcoffset() is not None


def _normalize_ids(values: Any, *, field_name: str) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        raise ValueError(f"{field_name} must be a list of non-empty chunk IDs")
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ValueError(f"{field_name} must contain non-empty chunk IDs")
        chunk_id = str(value).strip()
        if not chunk_id:
            raise ValueError(f"{field_name} must contain non-empty chunk IDs")
        if chunk_id not in seen:
            seen.add(chunk_id)
            normalized.append(chunk_id)
    return normalized


def _normalize_gold_ids(values: Any) -> list[str]:
    """Normalize binary or graded qrels, retaining only positively relevant IDs."""
    if isinstance(values, dict):
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_id, grade in values.items():
            if isinstance(raw_id, bool) or not isinstance(raw_id, (str, int)):
                raise ValueError("relevant_chunk_ids must contain valid chunk IDs")
            chunk_id = str(raw_id).strip()
            if not chunk_id:
                raise ValueError("relevant_chunk_ids must contain valid chunk IDs")
            if isinstance(grade, bool) or not isinstance(grade, int) or grade < 0:
                raise ValueError("relevance grades must be non-negative integers")
            if grade > 0 and chunk_id not in seen:
                seen.add(chunk_id)
                normalized.append(chunk_id)
        return normalized
    return _normalize_ids(values, field_name="relevant_chunk_ids")


def evaluate(records, k=5):
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive integer")
    if not isinstance(records, (list, tuple)) or not records or not all(
        isinstance(record, dict)
        and record.get("label_status") == "reviewed"
        and has_human_review_attestation(record)
        for record in records
    ):
        return {
            "status": "BLOCKED",
            "reason": "HUMAN_REVIEWED_LABELS_AND_ATTESTATIONS_REQUIRED",
            "metrics": None,
        }

    recall, mrr = [], []
    aggregates = {
        key: [0, 0]
        for key in (
            "citation_accuracy",
            "claim_evidence_precision",
            "extraction_completeness",
            "classification_accuracy",
            "contradiction_precision",
            "unsupported_claim_rate",
        )
    }
    for row in records:
        gold = set(_normalize_gold_ids(row.get("relevant_chunk_ids")))
        if not gold:
            raise ValueError("Reviewed evaluation cases must contain at least one relevant chunk")

        retrieved = _normalize_ids(
            row.get("retrieved_chunk_ids", []),
            field_name="retrieved_chunk_ids",
        )
        found = retrieved[:k]
        recall.append(len(gold.intersection(found)) / len(gold))
        mrr.append(
            next(
                (1 / rank for rank, chunk_id in enumerate(found, 1) if chunk_id in gold),
                0,
            )
        )

        reviewed_counts = row.get("reviewed_counts", {})
        if not isinstance(reviewed_counts, dict):
            raise ValueError("reviewed_counts must be a mapping")
        for name, pair in reviewed_counts.items():
            if (
                name not in aggregates
                or not isinstance(pair, (list, tuple))
                or len(pair) != 2
                or any(type(value) is not int or value < 0 for value in pair)
                or pair[0] > pair[1]
            ):
                raise ValueError("Invalid reviewed metric counts")
            aggregates[name][0] += pair[0]
            aggregates[name][1] += pair[1]

    result_metrics = {
        f"recall@{k}": sum(recall) / len(recall),
        "MRR": sum(mrr) / len(mrr),
    }
    result_metrics.update(
        {
            name: numerator / denominator if denominator else None
            for name, (numerator, denominator) in aggregates.items()
        }
    )
    return {
        "status": "MEASURED_ON_SUPPLIED_REVIEWED_LABELS",
        "scored_cases": len(records),
        "metrics": result_metrics,
        "note": (
            "This evaluator validates the review evidence envelope, not reviewer identity. "
            "Production must verify reviewer_id against the authoritative reviewer registry "
            "and bind the reviewed dataset, rubric, and corpus hashes to an immutable audit record."
        ),
    }
