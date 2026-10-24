"""BM25 + pgvector + RRF, metadata filters and citation-safe extractive answers.

This API returns source excerpts, never manufactures an LLM answer or page.
Graph expansion includes reviewed edges only; graph evidence never replaces sources.
"""

from __future__ import annotations
from collections import Counter
import json
import math
import re
from im19.contracts import PipelineError

EMBED_MODEL = "intfloat/multilingual-e5-small"


def validate_vector(vector):
    if len(vector) != 384 or any(
        isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x)
        for x in vector
    ):
        raise PipelineError("FAILED", "INVALID_EMBEDDING")
    norm = math.sqrt(sum(x * x for x in vector))
    if not 0.98 <= norm <= 1.02:
        raise PipelineError("FAILED", "EMBEDDING_NOT_NORMALIZED")


def rrf(*rankings, k=60):
    scores, rows = {}, {}
    for ranking in rankings:
        seen = set()
        for rank, row in enumerate(ranking, 1):
            cid = str(row["chunk_id"])
            if cid in seen:
                continue
            seen.add(cid)
            scores[cid] = scores.get(cid, 0) + 1 / (k + rank)
            rows[cid] = row
    return [
        {**rows[cid], "rrf_score": scores[cid]}
        for cid in sorted(scores, key=lambda x: (-scores[x], x))
    ]


def tokens(text):
    return re.findall(r"\w+", text.casefold())


def bm25(query, rows, *, k1=1.5, b=0.75):
    """Exact BM25 over the bounded filtered corpus, not a renamed tsvector rank."""
    if not rows:
        return []
    terms = set(tokens(query))
    counts = [Counter(tokens(row["text_content"])) for row in rows]
    lengths = [sum(c.values()) for c in counts]
    avg = sum(lengths) / len(rows) or 1
    df = {term: sum(term in c for c in counts) for term in terms}
    ranked = []
    for row, c, length in zip(rows, counts, lengths, strict=True):
        score = 0
        for term in terms:
            freq = c[term]
            if freq:
                idf = math.log(1 + (len(rows) - df[term] + 0.5) / (df[term] + 0.5))
                score += (
                    idf * freq * (k1 + 1) / (freq + k1 * (1 - b + b * length / avg))
                )
        if score > 0:
            ranked.append({**row, "bm25_score": score})
    return sorted(ranked, key=lambda r: (-r["bm25_score"], str(r["chunk_id"])))


class E5Embedder:
    def __init__(self, model_path=EMBED_MODEL):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(
            model_path, device="cpu", local_files_only=True, trust_remote_code=False
        )
        self.version = EMBED_MODEL

    def passages(self, texts):
        for text in texts:
            if len(self.model.tokenizer.encode("passage: " + text)) > 512:
                raise PipelineError("NEEDS_HUMAN_REVIEW", "EMBEDDING_TOKEN_QUOTA")
        values = self.model.encode(
            ["passage: " + t for t in texts],
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()
        for vector in values:
            validate_vector(vector)
        return values

    def query(self, text):
        if len(self.model.tokenizer.encode("query: " + text)) > 512:
            raise PipelineError("NEEDS_HUMAN_REVIEW", "QUERY_TOKEN_QUOTA")
        vector = self.model.encode(
            ["query: " + text], normalize_embeddings=True, show_progress_bar=False
        )[0].tolist()
        validate_vector(vector)
        return vector


class HybridRetriever:
    def __init__(self, store, embedder, *, max_corpus_chunks=20000, reranker=None):
        self.store, self.embedder = store, embedder
        self.max_corpus_chunks, self.reranker = max_corpus_chunks, reranker

    def search(self, query, *, filters=None, limit=5, graph=False):
        if (
            not isinstance(query, str)
            or not query.strip()
            or len(query) > 2000
            or not 1 <= limit <= 20
        ):
            raise ValueError("Invalid query/limit")
        filters = filters or {}
        allowed = {
            "document_id",
            "title",
            "author",
            "category",
            "concept",
            "page_start",
            "page_end",
            "review_status",
            "source_credibility_min",
        }
        if set(filters) - allowed:
            raise ValueError("Unknown metadata filter")
        conditions = [
            "v.state='PUBLISHED'",
            "NOT f.deleted",
            "f.access_authorized",
            "v.revision=f.revision",
            "v.source_content_hash=f.content_hash",
        ]
        params = []
        for key, value in filters.items():
            if key == "document_id":
                conditions.append("v.id=%s")
                params.append(value)
            elif key == "title":
                conditions.append("f.filename ILIKE %s")
                params.append("%" + value + "%")
            elif key == "author":
                conditions.append("f.metadata->>'author'=%s")
                params.append(value)
            elif key in {"category", "concept", "review_status"}:
                conditions.append(
                    "EXISTS(SELECT 1 FROM im19.knowledge_units u WHERE u.document_id=v.id AND u."
                    + key
                    + "=%s)"
                )
                params.append(value)
            elif key == "source_credibility_min":
                conditions.append(
                    "(v.review->'dimensions'->>'source_credibility')::float8>=%s"
                )
                params.append(value)
            else:
                conditions.append(
                    "c.page_start>=%s" if key == "page_start" else "c.page_end<=%s"
                )
                params.append(value)
        where = " AND ".join(conditions)
        base = (
            " FROM im19.chunks c JOIN im19.document_versions v ON v.id=c.document_id "
            "JOIN im19.source_files f ON f.id=v.source_file_id WHERE " + where
        )
        fields = "c.id AS chunk_id,c.document_id,c.locator,c.page_start,c.page_end,c.text_content,c.content_hash,f.filename AS title,f.source_uri,v.review"
        with self.store.tx() as conn:
            # Count before transfer; exceeding quota abstains instead of truncating BM25 silently.
            count = conn.execute("SELECT count(*) AS n" + base, params).fetchone()["n"]
            if count > self.max_corpus_chunks:
                raise PipelineError(
                    "NEEDS_HUMAN_REVIEW", "BM25_CORPUS_QUOTA_USE_METADATA_FILTERS"
                )
            rows = conn.execute(
                "SELECT " + fields + base + " ORDER BY c.id", params
            ).fetchall()
            keyword = bm25(query, rows)[:50]
            query_vector = self.embedder.query(query)
            vector_json = json.dumps(query_vector)
            dense = conn.execute(
                "SELECT "
                + fields
                + ",1-(e.embedding OPERATOR(extensions.<=>) %s::extensions.vector) AS similarity "
                "FROM im19.embeddings e JOIN im19.chunks c ON c.id=e.chunk_id JOIN im19.document_versions v ON v.id=c.document_id "
                "JOIN im19.source_files f ON f.id=v.source_file_id WHERE "
                + where
                + " AND e.model_version=%s AND e.content_hash=c.content_hash "
                "ORDER BY e.embedding OPERATOR(extensions.<=>) %s::extensions.vector LIMIT 50",
                [vector_json, *params, self.embedder.version, vector_json],
            ).fetchall()
            # Uncalibrated similarity is a ranking score, not proof of sufficient evidence.
            # Require lexical overlap to avoid returning unrelated nearest neighbours as evidence.
            dense = [
                r for r in dense if set(tokens(query)) & set(tokens(r["text_content"]))
            ]
            ranked = rrf(keyword, dense)
            if graph and ranked:
                ids = [r["document_id"] for r in ranked[:limit]]
                expanded = conn.execute(
                    "SELECT DISTINCT " + fields + " FROM im19.knowledge_relations rel "
                    "JOIN im19.knowledge_units src ON src.id=rel.source_id JOIN im19.knowledge_units tgt ON tgt.id=rel.target_id "
                    "JOIN im19.chunks c ON c.id=ANY(tgt.source_chunk_ids) JOIN im19.document_versions v ON v.id=c.document_id "
                    "JOIN im19.source_files f ON f.id=v.source_file_id WHERE rel.review_status='reviewed' AND src.document_id=ANY(%s) AND "
                    + where
                    + " LIMIT 20",
                    [ids, *params],
                ).fetchall()
                ranked = rrf(ranked, expanded)
        if self.reranker:
            ranked = self.reranker(query, ranked)
        evidence = []
        for row in ranked[:limit]:
            page = row["page_start"]
            locator = row["locator"]
            valid = (
                type(page) is int
                and page > 0
                and row["page_end"] == page
                and locator == f"pdf:page:{page}"
            ) or (
                page is None
                and row["page_end"] is None
                and locator.startswith("epub:spine:")
            )
            if not valid:
                continue
            evidence.append(
                {
                    "chunk_id": str(row["chunk_id"]),
                    "document_id": str(row["document_id"]),
                    "title": row["title"],
                    "page": page,
                    "locator": locator,
                    "source_uri": row["source_uri"],
                    "content_hash": row["content_hash"],
                    "excerpt": row["text_content"],
                    "citation": f"{row['title']}, p. {page}"
                    if page
                    else f"{row['title']}, {locator}",
                    "verification_status": "NOT_EXTERNALLY_VERIFIED",
                }
            )
        return {
            "status": "EVIDENCE_FOUND" if evidence else "INSUFFICIENT_EVIDENCE",
            "query": query,
            "evidence": evidence,
            "answer_mode": "source_excerpts_only",
            "limitations": [
                "Evidence relevance and factual truth require assessment; lexical overlap is a conservative pilot gate."
            ],
        }
