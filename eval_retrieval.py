#!/usr/bin/env python3
"""Retrieval benchmark runner; metrics require reviewed labels and review evidence."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from im19.evaluation import has_human_review_attestation
from rag_pipeline import MODEL_ID, RAGClient, load_embedding_model

load_dotenv()


def _normalize_chunk_id(value: Any, *, field_name: str) -> str:
    """Normalize a chunk identifier while rejecting empty and boolean placeholders."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{field_name} must contain non-empty chunk IDs")
    chunk_id = str(value).strip()
    if not chunk_id:
        raise ValueError(f"{field_name} must contain non-empty chunk IDs")
    return chunk_id


def normalize_reviewed_qrels(case: dict[str, Any]) -> dict[str, int]:
    """Return relevance labels only after review status and evidence envelope validation."""
    if not isinstance(case, dict):
        raise ValueError("Reviewed qrels require a case mapping")

    raw = case.get("relevant_chunk_ids", {})
    label_status = str(case.get("label_status", "")).strip().lower()
    if label_status != "reviewed":
        return {}

    if not has_human_review_attestation(case):
        raise ValueError("Reviewed qrels require a matching human review evidence envelope")
    if raw is None:
        raise ValueError("Reviewed relevant_chunk_ids cannot be null")

    if isinstance(raw, (list, tuple, set)):
        qrels: dict[str, int] = {}
        for chunk_id in raw:
            normalized_id = _normalize_chunk_id(
                chunk_id, field_name="relevant_chunk_ids list"
            )
            if normalized_id in qrels:
                continue
            qrels[normalized_id] = 1
        if not qrels:
            raise ValueError("Reviewed qrels must contain at least one relevant chunk")
        return qrels

    if not isinstance(raw, dict):
        raise ValueError("Reviewed relevant_chunk_ids must be a mapping or list")

    qrels = {}
    for chunk_id, grade in raw.items():
        normalized_id = _normalize_chunk_id(chunk_id, field_name="qrels keys")
        if isinstance(grade, bool) or not isinstance(grade, int) or grade < 0:
            raise ValueError("Reviewed qrels grades must be non-negative integers")
        qrels[normalized_id] = grade

    if not any(grade > 0 for grade in qrels.values()):
        raise ValueError("Reviewed qrels must contain at least one relevant chunk")
    return qrels


def validate_eval_cases(cases: Any) -> list[dict[str, Any]]:
    """Validate the benchmark dataset before opening database/model connections."""
    if not isinstance(cases, list) or not cases:
        raise ValueError("Evaluation cases must be a non-empty JSON list")

    seen_query_ids: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"Evaluation case at index {index} must be an object")
        query_id = case.get("query_id")
        query = case.get("query")
        label_status = case.get("label_status")
        if (
            not isinstance(query_id, str)
            or not query_id.strip()
            or query_id != query_id.strip()
        ):
            raise ValueError(f"Evaluation case at index {index} requires a canonical query_id")
        if query_id in seen_query_ids:
            raise ValueError(f"Duplicate evaluation query_id: {query_id}")
        seen_query_ids.add(query_id)
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"Evaluation case {query_id} requires a non-empty query")
        if not isinstance(label_status, str) or not label_status.strip():
            raise ValueError(f"Evaluation case {query_id} requires label_status")

        raw_qrels = case.get("relevant_chunk_ids", {})
        if label_status.strip().lower() == "reviewed":
            normalize_reviewed_qrels(case)
        elif not isinstance(raw_qrels, (dict, list, tuple)):
            raise ValueError(
                f"Unreviewed relevant_chunk_ids for {query_id} must be a mapping or list"
            )
    return cases


def evaluation_case_status(
    case: dict[str, Any], qrels: dict[str, int] | None = None
) -> str:
    """Classify a validated case without treating unreviewed labels as gold."""
    label_status = str(case.get("label_status", "")).strip().lower()
    raw_qrels = case.get("relevant_chunk_ids", {})
    if label_status != "reviewed" and raw_qrels:
        return "labels_not_reviewed"
    gold = normalize_reviewed_qrels(case) if qrels is None else qrels
    return "scored" if gold else "needs_human_qrels"


def summarize_evaluation_coverage(statuses: list[str]) -> dict[str, Any]:
    """Separate human-review coverage from metric-eligible query coverage."""
    allowed = {"labels_not_reviewed", "needs_human_qrels", "scored"}
    if not isinstance(statuses, list) or any(status not in allowed for status in statuses):
        raise ValueError("evaluation case statuses are invalid")
    total = len(statuses)
    counts = {status: statuses.count(status) for status in allowed}
    scored = counts["scored"]
    reviewed = scored
    if scored == 0:
        overall = "blocked_no_human_reviewed_labels"
    elif scored == total:
        overall = "scored"
    else:
        overall = "partial_or_unlabeled"
    return {
        "scored_case_count": scored,
        "total_case_count": total,
        "reviewed_case_count": reviewed,
        "unreviewed_case_count": total - reviewed,
        "labels_not_reviewed_count": counts["labels_not_reviewed"],
        "needs_human_qrels_count": counts["needs_human_qrels"],
        "review_coverage": reviewed / total if total else 0.0,
        "evaluation_coverage": scored / total if total else 0.0,
        "overall_status": overall,
    }


def metrics(
    retrieved_ids: list[str], qrels: dict[str, int], k: int
) -> dict[str, float]:
    """Calculate P@k, Recall@k, MRR@k and graded nDCG@k without duplicate-hit inflation."""
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive integer")
    if not isinstance(retrieved_ids, (list, tuple)):
        raise ValueError("retrieved_ids must be a list of chunk IDs")
    if not isinstance(qrels, dict):
        raise ValueError("qrels must be a mapping")

    normalized_qrels: dict[str, int] = {}
    for raw_id, grade in qrels.items():
        chunk_id = _normalize_chunk_id(raw_id, field_name="qrels keys")
        if chunk_id in normalized_qrels:
            raise ValueError("qrels contain duplicate normalized chunk IDs")
        if isinstance(grade, bool) or not isinstance(grade, int) or grade < 0:
            raise ValueError("qrels grades must be non-negative integers")
        normalized_qrels[chunk_id] = grade

    unique_retrieved: list[str] = []
    seen: set[str] = set()
    for raw_id in retrieved_ids:
        chunk_id = _normalize_chunk_id(raw_id, field_name="retrieved_ids")
        if chunk_id not in seen:
            seen.add(chunk_id)
            unique_retrieved.append(chunk_id)

    top = unique_retrieved[:k]
    rels = [normalized_qrels.get(chunk_id, 0) for chunk_id in top]
    hits = sum(1 for relevance in rels if relevance > 0)
    total_relevant = sum(1 for relevance in normalized_qrels.values() if relevance > 0)
    reciprocal_rank = next(
        (1.0 / rank for rank, relevance in enumerate(rels, start=1) if relevance > 0),
        0.0,
    )
    dcg = sum(
        (2**relevance - 1) / math.log2(rank + 1)
        for rank, relevance in enumerate(rels, start=1)
    )
    ideal = sorted(normalized_qrels.values(), reverse=True)[:k]
    idcg = sum(
        (2**relevance - 1) / math.log2(rank + 1)
        for rank, relevance in enumerate(ideal, start=1)
    )
    return {
        f"precision@{k}": hits / k,
        f"recall@{k}": hits / total_relevant if total_relevant else 0.0,
        f"mrr@{k}": reciprocal_rank,
        f"ndcg@{k}": dcg / idcg if idcg else 0.0,
    }

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="eval_cases.json")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--out-dir", default="eval_results")
    args = parser.parse_args()
    if args.k < 1:
        parser.error("--k must be >=1")

    cases_path = Path(args.cases)
    try:
        raw_dataset = cases_path.read_bytes()
        cases = validate_eval_cases(json.loads(raw_dataset))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(f"Invalid evaluation dataset: {exc}")
    dataset_sha256 = hashlib.sha256(raw_dataset).hexdigest()

    # Dataset validation deliberately happens before credentials, network, or model loading.
    client = RAGClient()
    model = load_embedding_model()
    output: dict[str, Any] = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": MODEL_ID,
        "k": args.k,
        "dataset_sha256": dataset_sha256,
        "label_policy": (
            "Only reviewed cases with a matching human review evidence envelope are scored. "
            "The envelope is not cryptographic proof of reviewer identity."
        ),
        "cases": [],
    }
    rows_for_csv = []
    case_statuses: list[str] = []
    per_method_metrics: dict[str, list[dict[str, float]]] = {
        "keyword": [],
        "semantic": [],
    }

    for case in cases:
        query_id = case["query_id"]
        query = case["query"]
        gold = normalize_reviewed_qrels(case)
        label_status = case["label_status"]
        case_status = evaluation_case_status(case, gold)
        case_statuses.append(case_status)

        keyword = client.rpc(
            "rag_worker_match_keyword",
            {"p_query_text": query, "p_match_count": args.k, "p_min_rank": 0},
        ) or []
        query_vector = model.encode(
            ["query: " + query],
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )[0]
        semantic = client.rpc(
            "rag_worker_match_semantic",
            {
                "p_query_embedding": [round(float(value), 7) for value in query_vector],
                "p_match_count": args.k,
                "p_min_similarity": 0,
            },
        ) or []

        case_out: dict[str, Any] = {
            "query_id": query_id,
            "query": query,
            "label_status": label_status,
            "gold_label_count": len(gold),
            "status": case_status,
            "results": {},
        }
        for method, result_rows in (("keyword", keyword), ("semantic", semantic)):
            normalized = []
            for rank, row in enumerate(result_rows, start=1):
                chunk_id = _normalize_chunk_id(
                    row.get("chunk_id"), field_name=f"{method} result chunk_id"
                )
                item = {
                    "rank": rank,
                    "chunk_id": chunk_id,
                    "document_id": row.get("document_id"),
                    "document_name": row.get("document_name"),
                    "source_path": row.get("source_path"),
                    "chunk_index": row.get("chunk_index"),
                    "page_start": row.get("page_start"),
                    "page_end": row.get("page_end"),
                    "score": row.get("rank") if method == "keyword" else row.get("similarity"),
                    "text_excerpt": (row.get("text_content") or "")[:500],
                }
                normalized.append(item)
                rows_for_csv.append({"query_id": query_id, "method": method, **item})
            case_out["results"][method] = normalized
            if gold:
                result_metrics = metrics(
                    [row["chunk_id"] for row in normalized], gold, args.k
                )
                case_out.setdefault("metrics", {})[method] = result_metrics
                per_method_metrics[method].append(result_metrics)
        output["cases"].append(case_out)

    output["macro_metrics"] = {}
    for method, method_metrics in per_method_metrics.items():
        output["macro_metrics"][method] = (
            {
                key: sum(item[key] for item in method_metrics) / len(method_metrics)
                for key in method_metrics[0]
            }
            if method_metrics
            else None
        )
    output.update(summarize_evaluation_coverage(case_statuses))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"retrieval_eval_{stamp}.json"
    csv_path = out_dir / f"retrieval_results_{stamp}.csv"
    json_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with csv_path.open("w", newline="", encoding="utf-8") as output_file:
        fields = [
            "query_id",
            "method",
            "rank",
            "chunk_id",
            "document_id",
            "document_name",
            "source_path",
            "chunk_index",
            "page_start",
            "page_end",
            "score",
            "text_excerpt",
        ]
        writer = csv.DictWriter(output_file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows_for_csv)
    print(
        json.dumps(
            {
                "status": output["overall_status"],
                "scored_cases": output["scored_case_count"],
                "total_cases": output["total_case_count"],
                "dataset_sha256": dataset_sha256,
                "macro_metrics": output["macro_metrics"],
                "json_report": str(json_path),
                "csv_results": str(csv_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
