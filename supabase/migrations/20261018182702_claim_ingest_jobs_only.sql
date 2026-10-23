-- Keep active ingest jobs idempotent and isolate the PDF ingestion worker from other job types.
-- The migration is safe with the current queue (verified empty before application).

CREATE UNIQUE INDEX IF NOT EXISTS ingest_jobs_one_active_job_per_document_type
ON rag.ingest_jobs (document_id, job_type)
WHERE document_id IS NOT NULL AND status IN ('queued', 'running');

CREATE OR REPLACE FUNCTION public.rag_worker_claim_ingest_jobs(
  p_worker_id text,
  p_limit integer DEFAULT 5,
  p_document_ids uuid[] DEFAULT NULL
)
RETURNS TABLE(
  job_id uuid,
  document_id uuid,
  job_type text,
  attempt_count integer,
  lease_expires_at timestamp with time zone
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO ''
AS $function$
BEGIN
  IF p_worker_id IS NULL OR length(btrim(p_worker_id)) = 0 THEN
    RAISE EXCEPTION 'p_worker_id is required' USING ERRCODE = '22023';
  END IF;

  UPDATE rag.ingest_jobs AS j
  SET status = 'failed',
      finished_at = now(),
      error_message = COALESCE(j.error_message, 'Worker lease expired after maximum attempts'),
      lease_owner = NULL,
      lease_expires_at = NULL,
      updated_at = now()
  WHERE j.job_type = 'ingest'
    AND j.status = 'running'
    AND j.lease_expires_at < now()
    AND j.attempt_count >= j.max_attempts
    AND (p_document_ids IS NULL OR j.document_id = ANY(p_document_ids));

  RETURN QUERY
  WITH candidates AS (
    SELECT j.id
    FROM rag.ingest_jobs AS j
    WHERE j.job_type = 'ingest'
      AND j.attempt_count < j.max_attempts
      AND (p_document_ids IS NULL OR j.document_id = ANY(p_document_ids))
      AND (
        j.status = 'queued'
        OR (j.status = 'running' AND j.lease_expires_at IS NOT NULL AND j.lease_expires_at < now())
      )
    ORDER BY j.created_at ASC
    LIMIT LEAST(GREATEST(COALESCE(p_limit, 5), 1), 20)
    FOR UPDATE SKIP LOCKED
  ),
  claimed AS (
    UPDATE rag.ingest_jobs AS j
    SET status = 'running',
        attempt_count = j.attempt_count + 1,
        started_at = now(),
        finished_at = NULL,
        lease_owner = p_worker_id,
        lease_expires_at = now() + interval '15 minutes',
        updated_at = now()
    FROM candidates AS c
    WHERE j.id = c.id
    RETURNING j.id, j.document_id, j.job_type, j.attempt_count, j.lease_expires_at
  )
  SELECT c.id, c.document_id, c.job_type, c.attempt_count, c.lease_expires_at
  FROM claimed AS c;
END;
$function$;

REVOKE ALL ON FUNCTION public.rag_worker_claim_ingest_jobs(text, integer, uuid[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.rag_worker_claim_ingest_jobs(text, integer, uuid[]) TO service_role;
