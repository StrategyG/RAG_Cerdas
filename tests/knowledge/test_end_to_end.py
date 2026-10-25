"""Real PostgreSQL + parser; deterministic AI/vector fixtures, no live providers."""

from unittest.mock import Mock
from uuid import uuid4
import pytest
import psycopg
from im19.orchestrator import Orchestrator
from im19.retrieval import HybridRetriever
from im19.knowledge_review.review_engine import WEIGHTS
from .test_postgres import discover, worker_store
from .test_processing import pdf


class FixtureModel:
    version = "deterministic-fixture-not-qwen"

    def json(self, rubric, payload):
        if "taxonomy" in payload:
            return {
                "labels": [{"category": "Trading", "subcategory": "Risk Management"}],
                "ambiguous": False,
            }
        if "source_text" in payload:
            return {
                "units": [
                    {
                        "concept": "Risk management",
                        "knowledge_type": "principle",
                        "claim": "Risk management protects capital.",
                        "evidence_text": "Risk management protects capital.",
                    }
                ]
            }
        return {
            "dimensions": {k: 90 for k in WEIGHTS},
            "findings": [],
            "risk": "low",
            "relations": [],
        }


class FixtureEmbedder:
    version = "intfloat/multilingual-e5-small"

    def passages(self, texts):
        return [[1.0] + [0.0] * 383 for _ in texts]

    def query(self, text):
        return [1.0] + [0.0] * 383


def test_full_pipeline_requires_separate_approval_then_publishes_searchable_citations(
    database, tmp_path
):
    data = pdf("Risk management protects capital.")
    doc, cid = discover(database, data=data)
    with database.tx() as conn:
        conn.execute("UPDATE im19.source_files SET access_authorized=true")
    worker = worker_store(database)
    dropbox = Mock()
    dropbox.download.return_value = data
    runner = Orchestrator(
        worker, dropbox, FixtureModel(), FixtureEmbedder(), workdir=tmp_path
    )
    assert runner.run_one()
    assert database.load(doc)["state"] == "NEEDS_HUMAN_REVIEW"
    retriever = HybridRetriever(worker, FixtureEmbedder())
    assert retriever.search("risk management")["status"] == "INSUFFICIENT_EVIDENCE"
    review_id = database.load(doc)["checkpoint"]["review_run_id"]
    with database.tx() as conn:
        conn.execute(
            "INSERT INTO im19.human_approvals(review_run_id,reviewer_id,decision,rationale) VALUES(%s,'fixture-human','approve','Synthetic fixture approved')",
            (review_id,),
        )
    assert worker.resume_approved() == 1
    assert runner.run_one()
    assert database.load(doc)["state"] == "PUBLISHED"
    result = retriever.search("risk management")
    assert result["status"] == "EVIDENCE_FOUND" and result["evidence"][0]["page"] == 1
    assert (
        "Book.pdf" in result["evidence"][0]["title"]
        or "book.pdf" in result["evidence"][0]["title"]
    )
    assert result["evidence"][0]["verification_status"] == "NOT_EXTERNALLY_VERIFIED"
    assert retriever.search("astronomy telescope")["status"] == "INSUFFICIENT_EVIDENCE"
    assert (
        retriever.search("risk", filters={"category": "Psikologi"})["status"]
        == "INSUFFICIENT_EVIDENCE"
    )
    cursor = worker.source_connection(cid)["cursor"]
    worker.commit_discovery_page(
        cid, cursor, "tombstone", [{"deleted": True, "path": "/book.pdf"}]
    )
    assert retriever.search("risk management")["status"] == "INSUFFICIENT_EVIDENCE"


def test_auth_blocked_preserves_stage_and_does_not_publish(database, tmp_path):
    from im19.contracts import PipelineError

    data = pdf()
    doc, _ = discover(database, data)
    with database.tx() as conn:
        conn.execute("UPDATE im19.source_files SET access_authorized=true")
    dropbox = Mock()
    dropbox.download.side_effect = PipelineError("AUTH_BLOCKED", "DROPBOX_UNAUTHORIZED")
    runner = Orchestrator(
        database, dropbox, FixtureModel(), FixtureEmbedder(), workdir=tmp_path
    )
    runner.run_one()
    assert database.load(doc)["state"] == "AUTH_BLOCKED"
    assert database.claim("other") is None


def test_multibatch_embedding_readback_and_source_hash_dedup(database):
    from im19.contracts import Chunk, Page, digest

    doc, _ = discover(database)
    job = database.claim("worker")
    pages = [Page(f"pdf:page:{i}", f"Risk management {i}", i) for i in (1, 2)]
    chunks = [
        Chunk(
            str(uuid4()),
            doc,
            p.locator,
            p.text,
            p.page_number,
            p.page_number,
            digest(p.text),
        )
        for p in pages
    ]
    database.save_extraction(job, pages, chunks)
    database.save_embeddings(
        job, chunks[:1], [[1.0] + [0.0] * 383], FixtureEmbedder.version
    )
    database.save_embeddings(
        job, chunks[1:], [[1.0] + [0.0] * 383], FixtureEmbedder.version
    )
    with database.tx() as conn:
        conn.execute(
            "UPDATE im19.document_versions SET state='PARSED' WHERE id=%s", (doc,)
        )
    other, _ = discover(database, source_id="id:duplicate", path="/copy.pdf")
    assert (
        database.duplicate_of(other, database.load(other)["source_content_hash"]) == doc
    )


def test_publication_gate_rejects_missing_approval_after_indexed(database):
    doc, _ = discover(database)
    with database.tx() as conn:
        conn.execute(
            "UPDATE im19.document_versions SET state='INDEXED' WHERE id=%s", (doc,)
        )
    with pytest.raises(psycopg.errors.RaiseException, match="publication"):
        with database.tx() as conn:
            conn.execute(
                "UPDATE im19.document_versions SET state='PUBLISHED' WHERE id=%s",
                (doc,),
            )


def test_unapproved_source_is_not_downloaded_and_resumes_after_separate_authorization(
    database, tmp_path
):
    data = pdf("Risk management protects capital.")
    doc, _ = discover(database, data)
    dropbox = Mock()
    dropbox.download.return_value = data
    runner = Orchestrator(
        database, dropbox, FixtureModel(), FixtureEmbedder(), workdir=tmp_path
    )
    runner.run_one(doc)
    assert database.load(doc)["state"] == "NEEDS_HUMAN_REVIEW"
    assert not dropbox.download.called
    with database.tx() as conn:
        conn.execute("UPDATE im19.source_files SET access_authorized=true")
    assert database.resume_approved() == 1
    runner.run_one(doc)
    assert dropbox.download.call_count == 1
    assert database.load(doc)["state"] == "NEEDS_HUMAN_REVIEW"
    assert database.load(doc)["checkpoint"].get("review_run_id")
