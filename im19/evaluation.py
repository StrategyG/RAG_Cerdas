"""Only explicitly human-reviewed records contribute to knowledge quality metrics."""

from __future__ import annotations


def evaluate(records, k=5):
    if not records or not all(
        r.get("label_status") == "reviewed" and r.get("reviewer_id") for r in records
    ):
        return {
            "status": "BLOCKED",
            "reason": "HUMAN_REVIEWED_LABELS_REQUIRED",
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
        gold = set(row.get("relevant_chunk_ids", []))
        found = list(dict.fromkeys(row.get("retrieved_chunk_ids", [])))[:k]
        if gold:
            recall.append(len(gold.intersection(found)) / len(gold))
            mrr.append(next((1 / r for r, c in enumerate(found, 1) if c in gold), 0))
        for name, pair in row.get("reviewed_counts", {}).items():
            if (
                name not in aggregates
                or len(pair) != 2
                or any(type(x) is not int or x < 0 for x in pair)
                or pair[0] > pair[1]
            ):
                raise ValueError("Invalid reviewed metric counts")
            aggregates[name][0] += pair[0]
            aggregates[name][1] += pair[1]
    metrics = {
        f"recall@{k}": sum(recall) / len(recall) if recall else None,
        "MRR": sum(mrr) / len(mrr) if mrr else None,
    }
    metrics.update({name: n / d if d else None for name, (n, d) in aggregates.items()})
    return {
        "status": "MEASURED_ON_SUPPLIED_REVIEWED_LABELS",
        "scored_cases": len(records),
        "metrics": metrics,
        "note": "No metric certifies factual truth; record dataset identity, adjudication and model hashes separately.",
    }
