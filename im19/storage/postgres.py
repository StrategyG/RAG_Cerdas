"""Transactional private-schema storage. Parameterized queries and fenced worker leases."""

from __future__ import annotations
from contextlib import contextmanager
import json
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from im19 import PIPELINE_VERSION
from im19.contracts import PipelineError, stable_id, digest, Page, Chunk, KnowledgeUnit


class PostgresStore:
    def __init__(self, dsn: str, *, allow_local_test=False):
        from psycopg.conninfo import conninfo_to_dict

        config = conninfo_to_dict(dsn)
        if not allow_local_test and config.get("sslmode") != "verify-full":
            raise PipelineError("AUTH_BLOCKED", "DATABASE_TLS_VERIFY_FULL_REQUIRED")
        self.dsn = dsn

    @contextmanager
    def tx(self):
        with psycopg.connect(
            self.dsn, row_factory=dict_row, connect_timeout=10
        ) as conn:
            conn.execute("SET LOCAL statement_timeout='30s'")
            conn.execute("SET LOCAL lock_timeout='5s'")
            yield conn

    def check_role(self):
        with self.tx() as conn:
            row = conn.execute(
                "SELECT rolsuper,rolbypassrls,pg_has_role(current_user,'im19_approver','member') AS approver,pg_has_role(current_user,'im19_worker','member') AS worker FROM pg_roles WHERE rolname=current_user"
            ).fetchone()
            if (
                row["rolsuper"]
                or row["rolbypassrls"]
                or row["approver"]
                or not row["worker"]
            ):
                raise PipelineError("AUTH_BLOCKED", "OVERPRIVILEGED_DATABASE_LOGIN")

    def audit(self, conn, document_id, event, details):
        conn.execute(
            "INSERT INTO im19.audit_events(document_id,event_type,details) VALUES(%s,%s,%s)",
            (document_id, event, Jsonb(details)),
        )

    def source_connection(self, connection_id):
        with self.tx() as conn:
            row = conn.execute(
                "SELECT * FROM im19.source_connections WHERE id=%s", (connection_id,)
            ).fetchone()
            if not row:
                raise PipelineError("AUTH_BLOCKED", "SOURCE_CONNECTION_MISSING")
            return row

    def block_connection(self, connection_id, status, code):
        with self.tx() as conn:
            conn.execute(
                "UPDATE im19.source_connections SET status=%s,last_error_code=%s,updated_at=now() WHERE id=%s",
                (status, code, connection_id),
            )
            self.audit(
                conn,
                None,
                "connection_blocked",
                {"connection_id": str(connection_id), "status": status, "code": code},
            )

    def commit_discovery_page(self, connection_id, previous_cursor, cursor, entries):
        with self.tx() as conn:
            source = conn.execute(
                "SELECT * FROM im19.source_connections WHERE id=%s FOR UPDATE",
                (connection_id,),
            ).fetchone()
            if source["cursor"] != previous_cursor:
                raise PipelineError("RETRY_PENDING", "CURSOR_CONFLICT")
            for entry in entries:
                if entry.get("folder"):
                    continue
                path = entry["path"]
                root = source["root_path"].lower().rstrip("/")
                if root and not (path == root or path.startswith(root + "/")):
                    raise PipelineError("AUTH_BLOCKED", "PATH_OUTSIDE_APPROVED_ROOT")
                if entry.get("deleted"):
                    # Directory tombstones invalidate all descendants without deleting records.
                    rows = conn.execute(
                        "UPDATE im19.source_files SET deleted=true WHERE connection_id=%s "
                        "AND (path=%s OR starts_with(path,%s)) RETURNING id",
                        (connection_id, path, path + "/"),
                    ).fetchall()
                    for row in rows:
                        conn.execute(
                            "UPDATE im19.document_versions SET state='SUPERSEDED' WHERE source_file_id=%s AND state<>'SUPERSEDED'",
                            (row["id"],),
                        )
                    continue
                file_id = str(uuid4())
                row = conn.execute(
                    "INSERT INTO im19.source_files(id,connection_id,source_file_id,path,filename,extension,size,content_hash,revision,"
                    "modified_time,discovered_at,source_uri,access_scope,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT(connection_id,source_file_id) DO UPDATE SET path=excluded.path,filename=excluded.filename,"
                    "extension=excluded.extension,size=excluded.size,content_hash=excluded.content_hash,revision=excluded.revision,"
                    "modified_time=excluded.modified_time,discovered_at=excluded.discovered_at,metadata=excluded.metadata,deleted=false RETURNING id",
                    (
                        file_id,
                        connection_id,
                        entry["source_file_id"],
                        path,
                        entry["filename"],
                        entry["extension"],
                        entry["size"],
                        entry["content_hash"],
                        entry["revision"],
                        entry["modified_time"],
                        entry["discovered_at"],
                        entry["source_uri"],
                        entry["access_scope"],
                        Jsonb(entry["download_metadata"]),
                    ),
                ).fetchone()
                if entry["extension"] not in {".pdf", ".epub"}:
                    continue
                version_id = stable_id(
                    str(row["id"]), entry["revision"], PIPELINE_VERSION
                )
                conn.execute(
                    "UPDATE im19.document_versions SET state='SUPERSEDED' WHERE source_file_id=%s "
                    "AND id<>%s AND state<>'SUPERSEDED'",
                    (row["id"], version_id),
                )
                new = conn.execute(
                    "INSERT INTO im19.document_versions(id,source_file_id,revision,source_content_hash,pipeline_version) "
                    "VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id",
                    (
                        version_id,
                        row["id"],
                        entry["revision"],
                        entry["content_hash"],
                        PIPELINE_VERSION,
                    ),
                ).fetchone()
                if new:
                    conn.execute(
                        "INSERT INTO im19.ingestion_jobs(id,document_id) VALUES(%s,%s)",
                        (stable_id(version_id, "job"), version_id),
                    )
                    self.audit(
                        conn,
                        version_id,
                        "document_discovered",
                        {"pipeline_version": PIPELINE_VERSION},
                    )
            # Invalidate queue ownership as part of the same source/cursor transaction.
            # A stale worker must not leave superseded work permanently running.
            conn.execute(
                "UPDATE im19.ingestion_jobs j SET status='blocked',last_error_code='SOURCE_SUPERSEDED',"
                "lease_owner=null,lease_token=null,lease_expires_at=null,updated_at=now() "
                "FROM im19.document_versions v WHERE v.id=j.document_id AND v.state='SUPERSEDED' "
                "AND j.status IN ('queued','retry','running')"
            )
            conn.execute(
                "UPDATE im19.source_connections SET cursor=%s,status='ACTIVE',last_error_code=null,updated_at=now() WHERE id=%s",
                (cursor, connection_id),
            )
            self.audit(
                conn,
                None,
                "discovery_checkpoint",
                {"connection_id": str(connection_id), "entry_count": len(entries)},
            )

    def duplicate_of(self, document_id, source_hash):
        with self.tx() as conn:
            row = conn.execute(
                "SELECT id FROM im19.document_versions WHERE source_content_hash=%s AND id<>%s "
                "AND state IN ('PARSED','MINED','REVIEWED','NEEDS_HUMAN_REVIEW','EMBEDDED','INDEXED','PUBLISHED') ORDER BY created_at LIMIT 1",
                (source_hash, document_id),
            ).fetchone()
            return str(row["id"]) if row else None

    def claim(self, worker_id, lease_seconds=60, document_id=None):
        with self.tx() as conn:
            dead = conn.execute(
                "UPDATE im19.ingestion_jobs SET status='dead',lease_owner=null,lease_token=null WHERE status IN ('running','retry') "
                "AND attempts>=max_attempts AND (lease_expires_at IS NULL OR lease_expires_at<now()) RETURNING document_id"
            ).fetchall()
            for row in dead:
                self.audit(conn, row["document_id"], "dead_letter", {})
            row = conn.execute(
                "WITH candidate AS (SELECT j.id FROM im19.ingestion_jobs j JOIN im19.document_versions v ON v.id=j.document_id "
                "WHERE j.attempts<j.max_attempts AND v.state<>'SUPERSEDED' AND (%s::uuid IS NULL OR v.id=%s::uuid) AND ((j.status IN ('queued','retry') AND j.available_at<=now()) "
                "OR (j.status='running' AND j.lease_expires_at<now())) ORDER BY j.available_at FOR UPDATE OF j SKIP LOCKED LIMIT 1) "
                "UPDATE im19.ingestion_jobs j SET status='running',attempts=attempts+1,lease_owner=%s,lease_token=%s,"
                "lease_expires_at=now()+make_interval(secs=>%s),updated_at=now() FROM candidate c WHERE j.id=c.id RETURNING j.*",
                (document_id, document_id, worker_id, uuid4(), lease_seconds),
            ).fetchone()
            return row

    def fence(self, conn, job):
        row = conn.execute(
            "SELECT j.id FROM im19.ingestion_jobs j JOIN im19.document_versions v ON v.id=j.document_id "
            "WHERE j.id=%s AND j.status='running' AND j.lease_token=%s AND j.lease_expires_at>now() AND v.state<>'SUPERSEDED' FOR UPDATE OF j,v",
            (job["id"], job["lease_token"]),
        ).fetchone()
        if not row:
            raise PipelineError("RETRY_PENDING", "LEASE_LOST")

    def heartbeat(self, job, lease_seconds=60):
        with self.tx() as conn:
            self.fence(conn, job)
            conn.execute(
                "UPDATE im19.ingestion_jobs SET lease_expires_at=now()+make_interval(secs=>%s) WHERE id=%s",
                (lease_seconds, job["id"]),
            )

    def load(self, document_id):
        with self.tx() as conn:
            row = conn.execute(
                "SELECT v.*,f.metadata AS source_metadata,f.extension,f.access_authorized,f.deleted,f.filename,f.source_uri "
                "FROM im19.document_versions v JOIN im19.source_files f ON f.id=v.source_file_id WHERE v.id=%s",
                (document_id,),
            ).fetchone()
            return row

    def checkpoint(self, job, old_state, new_state, patch=None, **columns):
        from im19.orchestrator import validate_transition

        validate_transition(old_state, new_state)
        if set(columns) - {"content_sha256", "classification", "review"}:
            raise ValueError("Unknown checkpoint column")
        from psycopg import sql

        with self.tx() as conn:
            self.fence(conn, job)
            assignments = [sql.SQL("state=%s"), sql.SQL("checkpoint=checkpoint || %s")]
            params = [new_state, Jsonb(patch or {})]
            for column, value in columns.items():
                assignments.append(sql.SQL("{}=%s").format(sql.Identifier(column)))
                params.append(Jsonb(value) if isinstance(value, dict) else value)
            params += [job["document_id"], old_state]
            result = conn.execute(
                sql.SQL(
                    "UPDATE im19.document_versions SET {} WHERE id=%s AND state=%s RETURNING id"
                ).format(sql.SQL(",").join(assignments)),
                params,
            ).fetchone()
            if not result:
                raise PipelineError("RETRY_PENDING", "STATE_CONFLICT")
            self.audit(
                conn,
                job["document_id"],
                "state_transition",
                {"from": old_state, "to": new_state},
            )

    def save_extraction(self, job, pages, chunks):
        with self.tx() as conn:
            self.fence(conn, job)
            for page in pages:
                conn.execute(
                    "INSERT INTO im19.document_pages VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (
                        job["document_id"],
                        page.locator,
                        page.page_number,
                        page.text,
                        digest(page.text),
                        Jsonb(page.blocks),
                        page.ocr_used,
                        page.ocr_confidence,
                        Jsonb(page.warnings),
                    ),
                )
            # A replay must agree with immutable extraction output already committed.
            persisted_pages = conn.execute(
                "SELECT locator,content_hash,page_number FROM im19.document_pages WHERE document_id=%s",
                (job["document_id"],),
            ).fetchall()
            actual = {
                p["locator"]: (p["content_hash"], p["page_number"])
                for p in persisted_pages
            }
            expected = {p.locator: (digest(p.text), p.page_number) for p in pages}
            if actual != expected:
                raise PipelineError("QUARANTINED", "EXTRACTION_REPLAY_MISMATCH")
            for c in chunks:
                conn.execute(
                    "INSERT INTO im19.chunks VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (
                        c.chunk_id,
                        c.document_id,
                        c.locator,
                        c.text,
                        c.page_start,
                        c.page_end,
                        c.content_hash,
                    ),
                )
            conn.execute(
                "INSERT INTO im19.extraction_runs(document_id,parser_version,stats) VALUES(%s,%s,%s)",
                (
                    job["document_id"],
                    PIPELINE_VERSION,
                    Jsonb({"pages": len(pages), "chunks": len(chunks)}),
                ),
            )

    def extraction(self, document_id):
        with self.tx() as conn:
            pages = [
                Page(
                    r["locator"],
                    r["text_content"],
                    r["page_number"],
                    r["structure"],
                    r["ocr_confidence"],
                    r["ocr_used"],
                    r["warnings"],
                )
                for r in conn.execute(
                    "SELECT * FROM im19.document_pages WHERE document_id=%s ORDER BY page_number NULLS LAST,locator",
                    (document_id,),
                )
            ]
            chunks = [
                Chunk(
                    str(r["id"]),
                    str(r["document_id"]),
                    r["locator"],
                    r["text_content"],
                    r["page_start"],
                    r["page_end"],
                    r["content_hash"],
                )
                for r in conn.execute(
                    "SELECT * FROM im19.chunks WHERE document_id=%s ORDER BY page_start NULLS LAST,locator,id",
                    (document_id,),
                )
            ]
            return pages, chunks

    def save_units(self, job, units):
        with self.tx() as conn:
            self.fence(conn, job)
            for u in units:
                conn.execute(
                    "INSERT INTO im19.knowledge_units(id,document_id,concept,category,subcategory,knowledge_type,claim,evidence_text,locator,"
                    "page_start,page_end,source_chunk_ids,model_version,content_hash) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::uuid[],%s,%s) ON CONFLICT DO NOTHING",
                    (
                        u.knowledge_id,
                        u.document_id,
                        u.concept,
                        u.category,
                        u.subcategory,
                        u.knowledge_type,
                        u.claim,
                        u.evidence_text,
                        u.locator,
                        u.page_start,
                        u.page_end,
                        u.source_chunk_ids,
                        u.model_version,
                        u.content_hash,
                    ),
                )
                conn.execute(
                    "INSERT INTO im19.knowledge_claims VALUES(%s,%s,'unknown','NOT_EXTERNALLY_VERIFIED') ON CONFLICT DO NOTHING",
                    (u.knowledge_id, u.knowledge_type),
                )
                eid = stable_id(u.knowledge_id, u.evidence_text)
                conn.execute(
                    "INSERT INTO im19.claim_evidence(id,claim_id,chunk_id,excerpt) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (eid, u.knowledge_id, u.source_chunk_ids[0], u.evidence_text),
                )
                # Nodes and attribution edges are deterministic, evidence-bound, never infer truth.
                nodes = [
                    (u.document_id, "Document", u.document_id),
                    (u.knowledge_id, "Claim", u.claim),
                    (eid, "Evidence", u.evidence_text),
                    (stable_id(u.document_id, u.concept), "Concept", u.concept),
                    (
                        stable_id(u.document_id, u.category, u.subcategory),
                        "Category",
                        u.category + "/" + u.subcategory,
                    ),
                ]
                if u.knowledge_type == "methodology":
                    nodes.append(
                        (
                            stable_id(u.knowledge_id, "methodology"),
                            "Methodology",
                            u.concept,
                        )
                    )
                for nid, kind, label in nodes:
                    conn.execute(
                        "INSERT INTO im19.knowledge_nodes(id,node_type,label,document_id) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (nid, kind, label, u.document_id),
                    )
                edges = [
                    (u.knowledge_id, u.document_id, "DERIVED_FROM"),
                    (eid, u.knowledge_id, "SUPPORTS"),
                    (
                        u.knowledge_id,
                        stable_id(u.document_id, u.concept),
                        "DEFINES" if u.knowledge_type == "definition" else "RELATED_TO",
                    ),
                    (
                        u.knowledge_id,
                        stable_id(u.document_id, u.category, u.subcategory),
                        "APPLIES_TO",
                    ),
                ]
                for src, tgt, kind in edges:
                    conn.execute(
                        "INSERT INTO im19.knowledge_relations(id,source_id,target_id,relation_type,evidence_id,model_version,review_status) "
                        "VALUES(%s,%s,%s,%s,%s,%s,'pending') ON CONFLICT DO NOTHING",
                        (
                            stable_id(src, tgt, kind),
                            src,
                            tgt,
                            kind,
                            eid,
                            u.model_version,
                        ),
                    )

    def units(self, document_id):
        with self.tx() as conn:
            rows = conn.execute(
                "SELECT * FROM im19.knowledge_units WHERE document_id=%s ORDER BY id",
                (document_id,),
            ).fetchall()
            return [
                KnowledgeUnit(
                    str(r["id"]),
                    str(r["document_id"]),
                    r["concept"],
                    r["category"],
                    r["subcategory"],
                    r["knowledge_type"],
                    r["claim"],
                    r["evidence_text"],
                    r["page_start"],
                    r["page_end"],
                    [str(x) for x in r["source_chunk_ids"]],
                    r["locator"],
                    r["model_version"],
                    r["content_hash"],
                )
                for r in rows
            ]

    def comparisons(self, document_id, limit=20):
        with self.tx() as conn:
            rows = conn.execute(
                "SELECT u.id AS knowledge_id,u.claim,u.evidence_text FROM im19.knowledge_units u "
                "JOIN im19.document_versions v ON v.id=u.document_id WHERE v.state='PUBLISHED' AND u.document_id<>%s "
                "AND EXISTS(SELECT 1 FROM im19.knowledge_units current_unit WHERE current_unit.document_id=%s AND current_unit.concept=u.concept) "
                "ORDER BY u.id LIMIT %s",
                (document_id, document_id, limit),
            ).fetchall()
            return [{**r, "knowledge_id": str(r["knowledge_id"])} for r in rows]

    def save_review(self, job, review, model_version):
        # Persist reviewer outputs once per version/model/rubric. Crash retries reuse it.
        rid = stable_id(str(job["document_id"]), model_version, "rubric-v2")
        with self.tx() as conn:
            self.fence(conn, job)
            inserted = conn.execute(
                "INSERT INTO im19.review_runs VALUES(%s,%s,%s,'rubric-v2',%s,now()) ON CONFLICT DO NOTHING RETURNING id",
                (rid, job["document_id"], model_version, Jsonb(review)),
            ).fetchone()
            if inserted:
                for finding in review["reviews"]:
                    conn.execute(
                        "INSERT INTO im19.review_findings(review_run_id,knowledge_id,role,finding) VALUES(%s,%s,%s,%s)",
                        (rid, finding["knowledge_id"], finding["role"], Jsonb(finding)),
                    )
                for edge in review["relations"]:
                    kind = (
                        "CONTRADICTS"
                        if edge["kind"] == "DIRECT_CONTRADICTION"
                        else "RELATED_TO"
                    )
                    conn.execute(
                        "INSERT INTO im19.knowledge_relations(id,source_id,target_id,relation_type,evidence_id,model_version,review_status,context) "
                        "VALUES(%s,%s,%s,%s,%s,%s,'pending',%s) ON CONFLICT DO NOTHING",
                        (
                            stable_id(
                                edge["source_id"], edge["target_id"], edge["kind"]
                            ),
                            edge["source_id"],
                            edge["target_id"],
                            kind,
                            edge["evidence_id"],
                            model_version,
                            Jsonb({"analysis_kind": edge["kind"]}),
                        ),
                    )
            stored = conn.execute(
                "SELECT result FROM im19.review_runs WHERE id=%s", (rid,)
            ).fetchone()["result"]
            return rid, stored

    def approval(self, review_id):
        with self.tx() as conn:
            row = conn.execute(
                "SELECT * FROM im19.human_approvals WHERE review_run_id=%s",
                (review_id,),
            ).fetchone()
            return {**row, "review_run_id": str(row["review_run_id"])} if row else None

    def save_embeddings(self, job, chunks, vectors, model_version):
        from im19.retrieval import validate_vector

        if len(chunks) != len(vectors):
            raise PipelineError("FAILED", "EMBEDDING_COUNT_MISMATCH")
        with self.tx() as conn:
            self.fence(conn, job)
            for chunk, vec in zip(chunks, vectors, strict=True):
                validate_vector(vec)
                conn.execute(
                    "INSERT INTO im19.embeddings VALUES(%s,%s,%s,%s::extensions.vector) ON CONFLICT DO NOTHING",
                    (
                        chunk.chunk_id,
                        model_version,
                        chunk.content_hash,
                        json.dumps(vec),
                    ),
                )
            persisted = conn.execute(
                "SELECT count(*) AS n FROM im19.embeddings e JOIN im19.chunks c ON c.id=e.chunk_id "
                "WHERE c.document_id=%s AND c.id=ANY(%s::uuid[]) AND e.content_hash=c.content_hash AND e.model_version=%s",
                (job["document_id"], [c.chunk_id for c in chunks], model_version),
            ).fetchone()["n"]
            if persisted != len(chunks):
                raise PipelineError("FAILED", "EMBEDDING_READBACK_MISMATCH")

    def finish(self, job, status="done", error_code=None, retry_seconds=0):
        with self.tx() as conn:
            self.fence(conn, job)
            conn.execute(
                "UPDATE im19.ingestion_jobs SET status=%s,last_error_code=%s,available_at=now()+make_interval(secs=>%s),"
                "lease_owner=null,lease_token=null,lease_expires_at=null,updated_at=now() WHERE id=%s",
                (status, error_code, retry_seconds, job["id"]),
            )
            self.audit(conn, job["document_id"], "job_" + status, {"code": error_code})

    def resume_approved(self):
        with self.tx() as conn:
            authorized = conn.execute(
                "UPDATE im19.document_versions v SET state='DISCOVERED',checkpoint=v.checkpoint-'error_code' "
                "FROM im19.source_files f WHERE v.source_file_id=f.id AND f.access_authorized AND NOT f.deleted "
                "AND v.state='NEEDS_HUMAN_REVIEW' AND v.checkpoint->>'error_code'='ACCESS_AUTHORIZATION_REQUIRED' RETURNING v.id"
            ).fetchall()
            for row in authorized:
                conn.execute(
                    "UPDATE im19.ingestion_jobs SET status='queued',attempts=0,available_at=now() WHERE document_id=%s AND status='blocked'",
                    (row["id"],),
                )
                self.audit(conn, row["id"], "source_access_approved", {})
            rows = conn.execute(
                "UPDATE im19.ingestion_jobs j SET status='queued',attempts=0,available_at=now() FROM im19.document_versions v "
                "JOIN im19.human_approvals a ON a.review_run_id=(v.checkpoint->>'review_run_id')::uuid "
                "WHERE j.document_id=v.id AND j.status='blocked' AND v.state='NEEDS_HUMAN_REVIEW' AND a.decision='approve' RETURNING j.document_id"
            ).fetchall()
            return len(rows) + len(authorized)
