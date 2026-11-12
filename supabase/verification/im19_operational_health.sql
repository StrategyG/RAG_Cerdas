-- Read-only private IM19 inspection; run with an authorized read role.
SELECT status,count(*) FROM im19.ingestion_jobs GROUP BY status;
SELECT state,count(*) FROM im19.document_versions GROUP BY state;
SELECT id,status,last_error_code,updated_at FROM im19.source_connections;
SELECT count(*) AS expired_leases FROM im19.ingestion_jobs WHERE status='running' AND lease_expires_at<now();
SELECT id,document_id,last_error_code,attempts FROM im19.ingestion_jobs WHERE status IN ('dead','blocked');
SELECT document_id,event_type,created_at FROM im19.audit_events ORDER BY id DESC LIMIT 50;
