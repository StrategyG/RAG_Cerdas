"""Explicit pilot/worker entry points. Never applies migrations automatically."""

import argparse
import json
import os
from im19.contracts import PipelineError
from im19.secrets import MountedSecrets, ColabSecrets
from im19.storage.postgres import PostgresStore
from im19.knowledge_mining.dropbox_discovery import DropboxClient, DropboxDiscovery


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "command", choices=["health", "discover", "pilot", "worker", "search", "purge-db", "purge-local"]
    )
    p.add_argument("--secret-provider", choices=["mounted", "colab"], default="mounted")
    p.add_argument("--connection-id")
    p.add_argument("--document-id")
    p.add_argument("--purge-request-id")
    p.add_argument("--query")
    p.add_argument("--filters", default="{}")
    p.add_argument("--max-pages", type=int, default=1)
    p.add_argument("--enable-ocr", action="store_true")
    args = p.parse_args()
    secrets = (
        ColabSecrets()
        if args.secret_provider == "colab"
        else MountedSecrets(os.getenv("IM19_SECRETS_DIR", "/run/secrets"))
    )
    try:
        store = PostgresStore(secrets.get("IM19_DATABASE_DSN"))
        store.check_role()
        if args.command == "purge-db":
            if not args.purge_request_id:
                p.error("--purge-request-id required")
            result = store.execute_approved_source_purge(args.purge_request_id)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result.get("status") in {"database_purged", "completed"} else 2
        if args.command == "purge-local":
            from im19.purge import purge_local_artifacts

            targets = store.claim_local_purge_targets()
            completed = 0
            failed = 0
            blob_removed = 0
            temp_removed = 0
            workflow_completed = 0
            for target in targets:
                try:
                    receipt = purge_local_artifacts(
                        os.getenv("IM19_WORKDIR", "/data/im19"),
                        str(target["document_version_id"]),
                        target["storage_node_id"],
                    )
                    status = store.record_local_purge_receipt(
                        target["request_id"],
                        target["document_version_id"],
                        receipt["blob_files_removed"],
                        receipt["temp_files_removed"],
                    )
                    if status == "completed":
                        workflow_completed += 1
                    completed += 1
                    blob_removed += receipt["blob_files_removed"]
                    temp_removed += receipt["temp_files_removed"]
                except PipelineError:
                    failed += 1
            print(json.dumps({
                "status": "processed" if failed == 0 else "partial",
                "targets_processed": completed + failed,
                "receipts_recorded": completed,
                "purge_requests_completed": workflow_completed,
                "failed": failed,
                "blob_files_removed": blob_removed,
                "temp_files_removed": temp_removed,
            }))
            return 0 if failed == 0 else 2
        if args.command == "health":
            with store.tx() as conn:
                rows = conn.execute(
                    "SELECT status,count(*) AS count FROM im19.ingestion_jobs GROUP BY status"
                ).fetchall()
            print(
                json.dumps(
                    {
                        "status": "DATABASE_REACHABLE",
                        "jobs": rows,
                        "production_ready": False,
                    }
                )
            )
            return 0
        if args.command in {"discover", "worker"} and not args.connection_id:
            p.error("--connection-id required")
        dropbox = DropboxClient(secrets)
        discovery = DropboxDiscovery(dropbox, store)
        if args.command == "discover":
            print(json.dumps(discovery.run(args.connection_id, args.max_pages)))
            return 0
        from im19.retrieval import E5Embedder, HybridRetriever

        embedder = E5Embedder(
            os.environ["IM19_EMBEDDING_PATH"],
            expected_sha256=os.environ["IM19_EMBEDDING_SHA256"],
        )
        if args.command == "search":
            if not args.query:
                p.error("--query required")
            print(
                json.dumps(
                    HybridRetriever(store, embedder).search(
                        args.query, filters=json.loads(args.filters)
                    ),
                    ensure_ascii=False,
                )
            )
            return 0
        from im19.local_model import LocalQwen
        from im19.orchestrator import Orchestrator

        model = LocalQwen(
            os.environ["IM19_GGUF_PATH"], model_sha256=os.environ["IM19_GGUF_SHA256"]
        )
        runner = Orchestrator(
            store,
            dropbox,
            model,
            embedder,
            workdir=os.getenv("IM19_WORKDIR", "/data/im19"),
            enable_ocr=args.enable_ocr,
        )
        if args.command == "pilot":
            if not args.document_id:
                p.error("--document-id required for one-document pilot")
            print(
                json.dumps(
                    {
                        "job_claimed": runner.run_one(args.document_id),
                        "production_ready": False,
                    }
                )
            )
            return 0
        runner.serve(discovery, args.connection_id)
        return 0
    except PipelineError as exc:
        print(json.dumps({"status": exc.status, "code": exc.code}))
        return 2
    except Exception:
        print(
            json.dumps({"status": "BLOCKED", "code": "CONFIGURATION_OR_SERVICE_ERROR"})
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
