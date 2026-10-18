#!/usr/bin/env python3
"""Retrieval benchmark runner; metrics are calculated only for manually labeled qrels."""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from rag_pipeline import RAGClient, MODEL_ID, load_embedding_model

load_dotenv()


def metrics(retrieved_ids: list[str], qrels: dict[str, int], k: int) -> dict[str, float]:
    """Calculate P@k, Recall@k, MRR@k and graded nDCG@k from reviewed relevance labels."""
    if k < 1:
        raise ValueError("k must be >= 1")
    top = retrieved_ids[:k]
    rels = [int(qrels.get(cid, 0)) for cid in top]
    hits = sum(1 for r in rels if r > 0)
    total_relevant = sum(1 for r in qrels.values() if r > 0)
    reciprocal_rank = 0.0
    for idx, relevance in enumerate(rels, start=1):
        if relevance > 0:
            reciprocal_rank = 1.0 / idx
            break
    import math
    dcg = sum((2**r - 1) / math.log2(i + 2) for i, r in enumerate(rels))
    ideal = sorted([int(v) for v in qrels.values()], reverse=True)[:k]
    idcg = sum((2**r - 1) / math.log2(i + 2) for i, r in enumerate(ideal))
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
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    client = RAGClient()
    model = load_embedding_model()
    output: dict[str, Any] = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": MODEL_ID,
        "k": args.k,
        "label_policy": "Only manually reviewed relevant_chunk_ids count toward metrics; no labels means metrics are withheld.",
        "cases": [],
    }
    rows_for_csv = []
    per_method_metrics: dict[str, list[dict[str, float]]] = {"keyword": [], "semantic": []}
    for case in cases:
        query_id = case["query_id"]
        query = case["query"]
        gold = case.get("relevant_chunk_ids", {})
        if isinstance(gold, list):
            gold = {str(chunk_id): 1 for chunk_id in gold}
        keyword = client.rpc("rag_worker_match_keyword", {
            "p_query_text": query, "p_match_count": args.k, "p_min_rank": 0,
        }) or []
        qvec = model.encode(["query: " + query], normalize_embeddings=True, convert_to_numpy=True,
                            show_progress_bar=False)[0]
        semantic = client.rpc("rag_worker_match_semantic", {
            "p_query_embedding": [round(float(x), 7) for x in qvec],
            "p_match_count": args.k,
            "p_min_similarity": 0,
        }) or []
        case_out: dict[str, Any] = {
            "query_id": query_id,
            "query": query,
            "gold_label_count": len(gold),
            "status": "scored" if gold else "needs_human_qrels",
            "results": {},
        }
        for method, results in (("keyword", keyword), ("semantic", semantic)):
            normalized = []
            for rank, row in enumerate(results, start=1):
                item = {
                    "rank": rank,
                    "chunk_id": row.get("chunk_id"),
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
                m = metrics([str(r.get("chunk_id")) for r in normalized], gold, args.k)
                case_out.setdefault("metrics", {})[method] = m
                per_method_metrics[method].append(m)
        output["cases"].append(case_out)

    output["macro_metrics"] = {}
    for method, method_metrics in per_method_metrics.items():
        output["macro_metrics"][method] = ({
            key: sum(m[key] for m in method_metrics) / len(method_metrics)
            for key in method_metrics[0]
        } if method_metrics else None)
    output["scored_case_count"] = sum(1 for case in cases if case.get("relevant_chunk_ids"))
    output["total_case_count"] = len(cases)
    output["overall_status"] = "scored" if output["scored_case_count"] == len(cases) else "partial_or_unlabeled"

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"retrieval_eval_{stamp}.json"
    csv_path = out_dir / f"retrieval_results_{stamp}.csv"
    json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        fields = ["query_id", "method", "rank", "chunk_id", "document_id", "document_name", "source_path", "chunk_index", "page_start", "page_end", "score", "text_excerpt"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows_for_csv)
    print(json.dumps({"status": output["overall_status"], "scored_cases": output["scored_case_count"],
                      "total_cases": output["total_case_count"], "macro_metrics": output["macro_metrics"],
                      "json_report": str(json_path), "csv_results": str(csv_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
