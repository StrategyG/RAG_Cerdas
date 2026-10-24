"""Durable stage machine with fenced leases, bounded retries and graceful shutdown."""

from __future__ import annotations
import hashlib
import os
from pathlib import Path
import random
import signal
import threading
import time
from uuid import uuid4
from im19.contracts import PipelineError
from im19.knowledge_mining.document_processor import parse_isolated, chunk_pages
from im19.knowledge_mining.classifier import Classifier
from im19.knowledge_mining.mining_engine import MiningEngine
from im19.knowledge_mining.dropbox_discovery import content_hash
from im19.knowledge_review.review_engine import ReviewEngine, publication_decision

STAGES = [
    "DISCOVERED",
    "VALIDATED",
    "DOWNLOADED",
    "PARSED",
    "MINED",
    "REVIEWED",
    "EMBEDDED",
    "INDEXED",
    "PUBLISHED",
]
INTERRUPTS = {
    "RETRY_PENDING",
    "AUTH_BLOCKED",
    "OCR_REQUIRED",
    "NEEDS_HUMAN_REVIEW",
    "QUARANTINED",
    "FAILED",
    "SUPERSEDED",
}


def validate_transition(old, new):
    if old == "SUPERSEDED" or old == "PUBLISHED" and new != "SUPERSEDED":
        raise ValueError("Terminal version transition")
    if new in INTERRUPTS:
        return
    if old == "NEEDS_HUMAN_REVIEW" and new == "REVIEWED":
        return
    if (
        old not in STAGES
        or STAGES.index(old) + 1 >= len(STAGES)
        or STAGES[STAGES.index(old) + 1] != new
    ):
        raise ValueError("Illegal pipeline transition")


class Orchestrator:
    def __init__(
        self,
        store,
        dropbox,
        model,
        embedder,
        *,
        workdir,
        enable_ocr=False,
        max_chunks=5000,
    ):
        self.store, self.dropbox, self.model, self.embedder = (
            store,
            dropbox,
            model,
            embedder,
        )
        self.root = Path(workdir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.enable_ocr, self.max_chunks = enable_ocr, max_chunks
        self.stop = threading.Event()
        self.worker_id = "im19-" + str(uuid4())

    def _blob(self, version_id):
        # All filenames are internal UUIDs, never a source filename/path.
        from uuid import UUID

        path = (self.root / (str(UUID(str(version_id))) + ".blob")).resolve()
        if not path.is_relative_to(self.root):
            raise PipelineError("QUARANTINED", "UNSAFE_BLOB_PATH")
        return path

    def _run(self, job):
        doc = self.store.load(job["document_id"])
        state = doc["state"]

        def step(new, patch=None, **columns):
            nonlocal state, doc
            self.store.checkpoint(job, state, new, patch, **columns)
            state = new
            doc = self.store.load(job["document_id"])
            if self.stop.is_set() and new != "PUBLISHED":
                raise PipelineError("RETRY_PENDING", "GRACEFUL_SHUTDOWN")

        if state == "DISCOVERED":
            if doc["deleted"] or doc["extension"] not in {".pdf", ".epub"}:
                raise PipelineError("SUPERSEDED", "SOURCE_INELIGIBLE")
            if not 0 < doc["source_metadata"]["size"] <= 64 * 1024**2:
                raise PipelineError("NEEDS_HUMAN_REVIEW", "FILE_SIZE_QUOTA")
            if not doc["access_authorized"]:
                raise PipelineError(
                    "NEEDS_HUMAN_REVIEW", "ACCESS_AUTHORIZATION_REQUIRED"
                )
            duplicate = self.store.duplicate_of(doc["id"], doc["source_content_hash"])
            if duplicate:
                step(
                    "NEEDS_HUMAN_REVIEW",
                    {"duplicate_of": duplicate, "error_code": "DUPLICATE_CONTENT"},
                )
                self.store.finish(job, "blocked", "DUPLICATE_CONTENT")
                return
            step("VALIDATED")
        if state == "VALIDATED":
            data = self.dropbox.download(doc["source_metadata"])
            path = self._blob(doc["id"])
            temp = path.with_suffix("." + str(job["lease_token"]) + ".tmp")
            try:
                with temp.open("xb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
            step("DOWNLOADED", content_sha256=hashlib.sha256(data).hexdigest())
        if state == "DOWNLOADED":
            path = self._blob(doc["id"])
            if not path.is_file():
                # Runtime storage may have been lost; re-download the pinned revision.
                data = self.dropbox.download(doc["source_metadata"])
            else:
                if path.stat().st_size > 64 * 1024**2:
                    raise PipelineError("QUARANTINED", "BLOB_SIZE_QUOTA")
                data = path.read_bytes()
            if (
                hashlib.sha256(data).hexdigest() != doc["content_sha256"]
                or content_hash(data) != doc["source_content_hash"]
            ):
                raise PipelineError("QUARANTINED", "CHECKPOINT_CONTENT_MISMATCH")
            pages = parse_isolated(data, doc["extension"], enable_ocr=self.enable_ocr)
            chunks = chunk_pages(str(doc["id"]), pages)
            if len(chunks) > self.max_chunks:
                raise PipelineError("NEEDS_HUMAN_REVIEW", "CHUNK_QUOTA")
            self.store.save_extraction(job, pages, chunks)
            step("PARSED")
        if state == "PARSED":
            pages, chunks = self.store.extraction(doc["id"])
            classification = Classifier(self.model).classify(chunks)
            units = MiningEngine(self.model).mine(chunks, classification)
            self.store.save_units(job, units)
            step("MINED", classification=classification)
        if state == "MINED":
            pages, chunks = self.store.extraction(doc["id"])
            review = ReviewEngine(self.model).review(
                self.store.units(doc["id"]),
                chunks,
                pages,
                self.store.comparisons(doc["id"]),
            )
            rid, review = self.store.save_review(job, review, self.model.version)
            step("REVIEWED", {"review_run_id": rid}, review=review)
        if state == "NEEDS_HUMAN_REVIEW":
            if not doc["checkpoint"].get("review_run_id"):
                raise PipelineError("NEEDS_HUMAN_REVIEW", "HUMAN_REMEDIATION_REQUIRED")
            if not self.store.approval(doc["checkpoint"]["review_run_id"]):
                raise PipelineError(
                    "NEEDS_HUMAN_REVIEW", "PUBLICATION_APPROVAL_REQUIRED"
                )
            step("REVIEWED")
        if state == "REVIEWED":
            decision = publication_decision(
                doc["review"],
                doc["classification"],
                access_authorized=doc["access_authorized"],
                human_approval=self.store.approval(doc["checkpoint"]["review_run_id"]),
            )
            if decision != "APPROVED_FOR_INDEXING":
                raise PipelineError(decision, "PUBLICATION_GATE")
            _, chunks = self.store.extraction(doc["id"])
            # Persist/read back embeddings in bounded batches; replay skips identical rows.
            for start in range(0, len(chunks), 16):
                batch = chunks[start : start + 16]
                vectors = self.embedder.passages([c.text for c in batch])
                self.store.save_embeddings(job, batch, vectors, self.embedder.version)
            step("EMBEDDED", {"embedding_model": self.embedder.version})
        if state == "EMBEDDED":
            step("INDEXED")
        if state == "INDEXED":
            # DB publication trigger independently checks the current source/review/approval/vector set.
            step("PUBLISHED")
        self.store.finish(job)

    def run_one(self, document_id=None):
        job = self.store.claim(self.worker_id, document_id=document_id)
        if not job:
            return False
        finished = threading.Event()
        lease_lost = threading.Event()

        def heartbeat():
            while not finished.wait(15):
                try:
                    self.store.heartbeat(job)
                except Exception:
                    lease_lost.set()
                    return

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            self._run(job)
        except PipelineError as exc:
            if exc.code == "LEASE_LOST" or lease_lost.is_set():
                return True  # New lease owner is authoritative; stale worker writes nothing.
            doc = self.store.load(job["document_id"])
            try:
                if exc.status != "RETRY_PENDING":
                    self.store.checkpoint(
                        job, doc["state"], exc.status, {"error_code": exc.code}
                    )
                status = (
                    "retry"
                    if exc.status == "RETRY_PENDING"
                    else "dead"
                    if exc.status in {"FAILED", "QUARANTINED", "SUPERSEDED"}
                    else "blocked"
                )
                self.store.finish(
                    job,
                    status,
                    exc.code,
                    min(300, 2 ** job["attempts"] + random.random()),
                )
            except PipelineError:
                pass
        except Exception:
            # Preserve last committed stage; no exception bodies or source snippets in logs.
            try:
                self.store.finish(
                    job, "retry", "WORKER_STAGE_FAILED", min(300, 2 ** job["attempts"])
                )
            except Exception:
                pass
        finally:
            finished.set()
            thread.join(timeout=2)
        return True

    def serve(self, discovery=None, connection_id=None, interval=300):
        def stop(signum, frame):
            self.stop.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        next_scan = 0
        while not self.stop.is_set():
            if discovery and time.monotonic() >= next_scan:
                try:
                    discovery.run(connection_id)
                except PipelineError:
                    pass  # Connection status/error is durable; other sources may proceed.
                next_scan = time.monotonic() + interval
            self.store.resume_approved()
            worked = self.run_one()
            self.stop.wait(0.1 if worked else 5)
