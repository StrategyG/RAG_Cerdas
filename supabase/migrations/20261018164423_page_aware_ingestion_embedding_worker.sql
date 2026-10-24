-- Additive Institutional RAG worker infrastructure.
-- Page-aware chunk replacement is atomic; every chunk must map to exactly one PDF page.
ALTER TABLE rag.ingest_jobs
  ADD COLUMN IF NOT EXISTS lease_owner text,
  ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz,
  ADD COLUMN IF NOT EXISTS max_attempts integer NOT NULL DEFAULT 5,
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

DO $constraints$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ingest_jobs_max_attempts_positive'
      AND conrelid = 'rag.ingest_jobs'::regclass
  ) THEN
    ALTER TABLE rag.ingest_jobs
      ADD CONSTRAINT ingest_jobs_max_attempts_positive CHECK (max_attempts BETWEEN 1 AND 20);
  END IF;
END
$constraints$;

CREATE INDEX IF NOT EXISTS ingest_jobs_queue_idx
  ON rag.ingest_jobs (status, created_at)
  WHERE status IN ('queued', 'running');

CREATE UNIQUE INDEX IF NOT EXISTS ingest_jobs_one_active_kind_per_document_idx
  ON rag.ingest_jobs (document_id, job_type)
  WHERE document_id IS NOT NULL AND status IN ('queued', 'running');

CREATE INDEX IF NOT EXISTS chunks_document_page_idx
  ON rag.chunks (document_id, page_start, page_end);

CREATE INDEX IF NOT EXISTS chunks_embedding_model_idx
  ON rag.chunks (embedding_model)
  WHERE embedding IS NOT NULL;

-- Server-side worker can list source metadata without exposing the private rag schema.
CREATE OR REPLACE FUNCTION public.rag_worker_list_documents(
  p_limit integer DEFAULT 100,
  p_status text DEFAULT 'discovered'
)
RETURNS TABLE (
  document_id uuid,
  source_path text,
  source_name text,
  content_sha256 text,
  file_size_bytes bigint,
  page_count integer,
  ingest_status text,
  metadata jsonb
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
  IF p_status NOT IN ('all', 'discovered', 'queued', 'processing', 'indexed', 'failed', 'skipped') THEN
    RAISE EXCEPTION 'Invalid ingest status: %', p_status USING ERRCODE = '22023';
  END IF;

  RETURN QUERY
  SELECT d.id, d.source_path, d.source_name, d.content_sha256,
         d.file_size_bytes, d.page_count, d.ingest_status, d.metadata
  FROM rag.documents AS d
  WHERE p_status = 'all' OR d.ingest_status = p_status
  ORDER BY d.updated_at ASC, d.created_at ASC
  LIMIT LEAST(GREATEST(COALESCE(p_limit, 100), 1), 200);
END;
$function$;

-- Queue work idempotently; active duplicate jobs are prevented by a partial unique index.
CREATE OR REPLACE FUNCTION public.rag_worker_enqueue_jobs(
  p_document_ids uuid[],
  p_job_type text DEFAULT 'ingest'
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
  v_inserted integer;
BEGIN
  IF p_job_type NOT IN ('ingest', 'embed', 'evaluation') THEN
    RAISE EXCEPTION 'Invalid job type: %', p_job_type USING ERRCODE = '22023';
  END IF;

  INSERT INTO rag.ingest_jobs (document_id, job_type, status, stats)
  SELECT DISTINCT d.id, p_job_type, 'queued', '{}'::jsonb
  FROM unnest(COALESCE(p_document_ids, ARRAY[]::uuid[])) AS requested(id)
  JOIN rag.documents AS d ON d.id = requested.id
  ON CONFLICT DO NOTHING;

  GET DIAGNOSTICS v_inserted = ROW_COUNT;
  RETURN v_inserted;
END;
$function$;

-- Lease jobs so multiple workers cannot claim the same queue row.
CREATE OR REPLACE FUNCTION public.rag_worker_claim_jobs(
  p_worker_id text,
  p_limit integer DEFAULT 5
)
RETURNS TABLE (
  job_id uuid,
  document_id uuid,
  job_type text,
  attempt_count integer,
  lease_expires_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
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
  WHERE j.status = 'running'
    AND j.lease_expires_at < now()
    AND j.attempt_count >= j.max_attempts;

  RETURN QUERY
  WITH candidates AS (
    SELECT j.id
    FROM rag.ingest_jobs AS j
    WHERE j.attempt_count < j.max_attempts
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

CREATE OR REPLACE FUNCTION public.rag_worker_finish_job(
  p_job_id uuid,
  p_worker_id text,
  p_success boolean,
  p_stats jsonb DEFAULT '{}'::jsonb,
  p_error text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
  v_rows integer;
  v_status text;
BEGIN
  UPDATE rag.ingest_jobs AS j
  SET status = CASE
        WHEN p_success THEN 'succeeded'
        WHEN j.attempt_count >= j.max_attempts THEN 'failed'
        ELSE 'queued'
      END,
      finished_at = CASE
        WHEN p_success OR j.attempt_count >= j.max_attempts THEN now()
        ELSE NULL
      END,
      error_message = CASE WHEN p_success THEN NULL ELSE left(COALESCE(p_error, 'Unspecified worker error'), 4000) END,
      stats = COALESCE(j.stats, '{}'::jsonb) || COALESCE(p_stats, '{}'::jsonb),
      lease_owner = NULL,
      lease_expires_at = NULL,
      updated_at = now()
  WHERE j.id = p_job_id
    AND j.status = 'running'
    AND j.lease_owner = p_worker_id;

  GET DIAGNOSTICS v_rows = ROW_COUNT;
  IF v_rows = 0 THEN
    RAISE EXCEPTION 'Job not found, not running, or owned by another worker'
      USING ERRCODE = '42501';
  END IF;

  SELECT j.status INTO v_status FROM rag.ingest_jobs AS j WHERE j.id = p_job_id;
  RETURN jsonb_build_object('job_id', p_job_id, 'status', v_status);
END;
$function$;

-- Atomic replacement for page-aware chunks. Each chunk belongs to exactly one real PDF page.
CREATE OR REPLACE FUNCTION public.rag_worker_replace_document_chunks(
  p_document_id uuid,
  p_page_count integer,
  p_chunks jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
  v_chunk_count integer;
  v_invalid_count integer;
BEGIN
  IF p_document_id IS NULL OR p_page_count IS NULL OR p_page_count < 1 THEN
    RAISE EXCEPTION 'document_id and a positive page_count are required' USING ERRCODE = '22023';
  END IF;
  IF jsonb_typeof(p_chunks) IS DISTINCT FROM 'array' OR jsonb_array_length(p_chunks) = 0 THEN
    RAISE EXCEPTION 'p_chunks must be a non-empty array; empty extraction must be handled as OCR/parse failure'
      USING ERRCODE = '22023';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM rag.documents AS d WHERE d.id = p_document_id) THEN
    RAISE EXCEPTION 'Unknown document_id: %', p_document_id USING ERRCODE = '23503';
  END IF;

  SELECT count(*) INTO v_invalid_count
  FROM jsonb_to_recordset(p_chunks) AS x(
    chunk_index integer,
    page_start integer,
    page_end integer,
    text_content text,
    token_count integer,
    content_sha256 text,
    metadata jsonb
  )
  WHERE x.chunk_index IS NULL OR x.chunk_index < 0
     OR x.page_start IS NULL OR x.page_end IS NULL
     OR x.page_start < 1 OR x.page_start > p_page_count
     OR x.page_end <> x.page_start
     OR length(btrim(COALESCE(x.text_content, ''))) = 0
     OR COALESCE(x.content_sha256, '') !~ '^[0-9a-fA-F]{64}$';

  IF v_invalid_count > 0 THEN
    RAISE EXCEPTION 'Rejected % invalid chunk(s): page mapping must be one page per chunk, text nonempty, SHA-256 required', v_invalid_count
      USING ERRCODE = '22023';
  END IF;

  SELECT jsonb_array_length(p_chunks) INTO v_chunk_count;

  IF EXISTS (
    SELECT 1
    FROM jsonb_to_recordset(p_chunks) AS x(
      chunk_index integer,
      page_start integer,
      page_end integer,
      text_content text,
      token_count integer,
      content_sha256 text,
      metadata jsonb
    )
    GROUP BY x.chunk_index
    HAVING count(*) > 1
  ) THEN
    RAISE EXCEPTION 'chunk_index values must be unique within one document' USING ERRCODE = '22023';
  END IF;

  DELETE FROM rag.chunks AS c WHERE c.document_id = p_document_id;

  INSERT INTO rag.chunks (
    document_id, chunk_index, page_start, page_end, text_content,
    token_count, content_sha256, metadata
  )
  SELECT p_document_id, x.chunk_index, x.page_start, x.page_end,
         x.text_content, x.token_count, x.content_sha256, COALESCE(x.metadata, '{}'::jsonb)
  FROM jsonb_to_recordset(p_chunks) AS x(
    chunk_index integer,
    page_start integer,
    page_end integer,
    text_content text,
    token_count integer,
    content_sha256 text,
    metadata jsonb
  );

  UPDATE rag.documents AS d
  SET page_count = p_page_count,
      ingest_status = 'processing',
      ingest_error = NULL,
      indexed_at = NULL,
      updated_at = now(),
      metadata = COALESCE(d.metadata, '{}'::jsonb) ||
        jsonb_build_object(
          'page_aware_ingest',
          jsonb_build_object(
            'version', 1,
            'page_count', p_page_count,
            'chunk_count', v_chunk_count,
            'page_mapping', 'one_pdf_page_per_chunk',
            'chunks_written_at', now()
          )
        )
  WHERE d.id = p_document_id;

  INSERT INTO rag.audit_events (event_type, document_id, details)
  VALUES (
    'page_aware_chunks_replaced',
    p_document_id,
    jsonb_build_object('page_count', p_page_count, 'chunk_count', v_chunk_count, 'page_mapping', 'one_pdf_page_per_chunk')
  );

  RETURN jsonb_build_object(
    'document_id', p_document_id,
    'page_count', p_page_count,
    'chunks_written', v_chunk_count,
    'page_mapped_chunks', v_chunk_count,
    'status', 'processing'
  );
END;
$function$;

-- Store vectors only if the current chunk hash still matches the hash embedded by the worker.
CREATE OR REPLACE FUNCTION public.rag_worker_store_embeddings(
  p_items jsonb,
  p_model text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
  v_item jsonb;
  v_expected integer := 0;
  v_updated integer := 0;
  v_stale integer := 0;
  v_rows integer;
  v_touched uuid[] := ARRAY[]::uuid[];
BEGIN
  IF p_model IS NULL OR length(btrim(p_model)) = 0 THEN
    RAISE EXCEPTION 'p_model is required' USING ERRCODE = '22023';
  END IF;
  IF jsonb_typeof(p_items) IS DISTINCT FROM 'array' OR jsonb_array_length(p_items) = 0 THEN
    RAISE EXCEPTION 'p_items must be a non-empty array' USING ERRCODE = '22023';
  END IF;

  FOR v_item IN SELECT value FROM jsonb_array_elements(p_items)
  LOOP
    v_expected := v_expected + 1;

    IF COALESCE(v_item->>'chunk_id', '') !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
       OR COALESCE(v_item->>'content_sha256', '') !~ '^[0-9a-fA-F]{64}$'
       OR jsonb_typeof(v_item->'embedding') IS DISTINCT FROM 'array'
       OR jsonb_array_length(v_item->'embedding') <> 384 THEN
      RAISE EXCEPTION 'Each embedding item requires chunk_id, SHA-256, and exactly 384 vector values'
        USING ERRCODE = '22023';
    END IF;

    UPDATE rag.chunks AS c
    SET embedding = ((v_item->'embedding')::text)::extensions.vector(384),
        embedding_model = p_model,
        embedded_at = now()
    WHERE c.id = (v_item->>'chunk_id')::uuid
      AND c.content_sha256 = v_item->>'content_sha256'
      AND c.page_start IS NOT NULL
      AND c.page_end = c.page_start;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    v_updated := v_updated + v_rows;
    IF v_rows = 0 THEN
      v_stale := v_stale + 1;
    ELSE
      v_touched := array_append(v_touched, (v_item->>'chunk_id')::uuid);
    END IF;
  END LOOP;

  UPDATE rag.documents AS d
  SET ingest_status = 'indexed',
      indexed_at = now(),
      updated_at = now(),
      ingest_error = NULL,
      metadata = COALESCE(d.metadata, '{}'::jsonb) ||
        jsonb_build_object('embedding_model', p_model, 'last_embedded_at', now())
  WHERE d.id IN (
    SELECT DISTINCT c.document_id
    FROM rag.chunks AS c
    WHERE c.id = ANY(v_touched)
  )
  AND d.page_count IS NOT NULL
  AND EXISTS (SELECT 1 FROM rag.chunks AS c WHERE c.document_id = d.id)
  AND NOT EXISTS (
    SELECT 1 FROM rag.chunks AS c
    WHERE c.document_id = d.id
      AND (
        c.embedding IS NULL
        OR c.embedding_model IS DISTINCT FROM p_model
        OR c.embedded_at IS NULL
        OR c.page_start IS NULL
        OR c.page_end <> c.page_start
      )
  );

  RETURN jsonb_build_object(
    'model', p_model,
    'received', v_expected,
    'stored', v_updated,
    'stale_or_unmapped', v_stale,
    'dimensions', 384
  );
END;
$function$;

-- Retrieval wrappers allow a server-side evaluator to use the private rag functions.
CREATE OR REPLACE FUNCTION public.rag_worker_match_keyword(
  p_query_text text,
  p_match_count integer DEFAULT 10,
  p_min_rank double precision DEFAULT 0
)
RETURNS TABLE (
  chunk_id uuid, document_id uuid, document_name text, source_path text,
  chunk_index integer, page_start integer, page_end integer,
  text_content text, content_sha256 text, rank double precision
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $function$
  SELECT * FROM rag.match_chunks_keyword(p_query_text, p_match_count, p_min_rank);
$function$;

CREATE OR REPLACE FUNCTION public.rag_worker_match_semantic(
  p_query_embedding jsonb,
  p_match_count integer DEFAULT 10,
  p_min_similarity double precision DEFAULT 0
)
RETURNS TABLE (
  chunk_id uuid, document_id uuid, document_name text, source_path text,
  chunk_index integer, page_start integer, page_end integer,
  text_content text, content_sha256 text, similarity double precision
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
  IF jsonb_typeof(p_query_embedding) IS DISTINCT FROM 'array'
     OR jsonb_array_length(p_query_embedding) <> 384 THEN
    RAISE EXCEPTION 'p_query_embedding must contain 384 values' USING ERRCODE = '22023';
  END IF;

  RETURN QUERY
  SELECT *
  FROM rag.match_chunks_semantic(
    (p_query_embedding::text)::extensions.vector(384),
    p_match_count,
    p_min_similarity
  );
END;
$function$;

REVOKE ALL ON FUNCTION public.rag_worker_list_documents(integer, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.rag_worker_enqueue_jobs(uuid[], text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.rag_worker_claim_jobs(text, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.rag_worker_finish_job(uuid, text, boolean, jsonb, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.rag_worker_replace_document_chunks(uuid, integer, jsonb) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.rag_worker_store_embeddings(jsonb, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.rag_worker_match_keyword(text, integer, double precision) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.rag_worker_match_semantic(jsonb, integer, double precision) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.rag_worker_list_documents(integer, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.rag_worker_enqueue_jobs(uuid[], text) TO service_role;
GRANT EXECUTE ON FUNCTION public.rag_worker_claim_jobs(text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.rag_worker_finish_job(uuid, text, boolean, jsonb, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.rag_worker_replace_document_chunks(uuid, integer, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.rag_worker_store_embeddings(jsonb, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.rag_worker_match_keyword(text, integer, double precision) TO service_role;
GRANT EXECUTE ON FUNCTION public.rag_worker_match_semantic(jsonb, integer, double precision) TO service_role;
