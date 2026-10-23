-- Non-destructive, versioned page-aware ingestion.
-- Existing rag.chunks rows are retained. A new generation becomes active only
-- after every chunk has a page mapping and a valid embedding.

CREATE OR REPLACE FUNCTION public.rag_worker_stage_document_generation(
  p_document_id uuid,
  p_page_count integer,
  p_chunks jsonb,
  p_document_sha256 text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO ''
AS $function$
DECLARE
  v_chunk_count integer;
  v_invalid_count integer;
  v_generation uuid := pg_catalog.gen_random_uuid();
  v_chunk_base bigint;
  v_max_input_index bigint;
BEGIN
  IF p_document_id IS NULL OR p_page_count IS NULL OR p_page_count < 1 THEN
    RAISE EXCEPTION 'document_id and a positive page_count are required'
      USING ERRCODE = '22023';
  END IF;

  IF COALESCE(p_document_sha256, '') !~ '^[0-9a-fA-F]{64}$' THEN
    RAISE EXCEPTION 'p_document_sha256 must be a 64-character SHA-256 hex digest'
      USING ERRCODE = '22023';
  END IF;

  IF jsonb_typeof(p_chunks) IS DISTINCT FROM 'array'
     OR jsonb_array_length(p_chunks) = 0 THEN
    RAISE EXCEPTION 'p_chunks must be a non-empty array; empty extraction must be handled as OCR/parse failure'
      USING ERRCODE = '22023';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM rag.documents AS d WHERE d.id = p_document_id
  ) THEN
    RAISE EXCEPTION 'Unknown document_id: %', p_document_id
      USING ERRCODE = '23503';
  END IF;

  SELECT count(*)::integer
  INTO v_invalid_count
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
    RAISE EXCEPTION 'Rejected % invalid chunk(s): page mapping must be one page per chunk, text nonempty, SHA-256 required',
      v_invalid_count USING ERRCODE = '22023';
  END IF;

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
    RAISE EXCEPTION 'chunk_index values must be unique within one document'
      USING ERRCODE = '22023';
  END IF;

  SELECT pg_catalog.max(c.chunk_index)::bigint + 1
  INTO v_chunk_base
  FROM rag.chunks AS c
  WHERE c.document_id = p_document_id;
  v_chunk_base := COALESCE(v_chunk_base, 0);

  SELECT pg_catalog.max(x.chunk_index)::bigint
  INTO v_max_input_index
  FROM jsonb_to_recordset(p_chunks) AS x(
    chunk_index integer,
    page_start integer,
    page_end integer,
    text_content text,
    token_count integer,
    content_sha256 text,
    metadata jsonb
  );

  IF v_chunk_base + COALESCE(v_max_input_index, 0) > 2147483647 THEN
    RAISE EXCEPTION 'Cannot append generation: chunk_index integer range exhausted'
      USING ERRCODE = '22003';
  END IF;

  v_chunk_count := jsonb_array_length(p_chunks);

  -- Append new rows with globally unique per-document chunk_index values.
  -- Do not delete or overwrite legacy/previous-generation chunks.
  INSERT INTO rag.chunks (
    document_id,
    chunk_index,
    page_start,
    page_end,
    text_content,
    token_count,
    content_sha256,
    metadata
  )
  SELECT
    p_document_id,
    (v_chunk_base + x.chunk_index)::integer,
    x.page_start,
    x.page_end,
    x.text_content,
    x.token_count,
    x.content_sha256,
    COALESCE(x.metadata, '{}'::jsonb)
      || pg_catalog.jsonb_build_object(
        'ingest_generation', v_generation::text,
        'chunking_version', 'page-aware-v1'
      )
  FROM jsonb_to_recordset(p_chunks) AS x(
    chunk_index integer,
    page_start integer,
    page_end integer,
    text_content text,
    token_count integer,
    content_sha256 text,
    metadata jsonb
  );

  -- Keep active metadata/page_count untouched while the new generation is pending.
  UPDATE rag.documents AS d
  SET ingest_status = 'processing',
      ingest_error = NULL,
      updated_at = pg_catalog.now(),
      metadata = pg_catalog.jsonb_set(
        COALESCE(d.metadata, '{}'::jsonb),
        '{page_aware_ingest}',
        COALESCE(d.metadata->'page_aware_ingest', '{}'::jsonb)
          || pg_catalog.jsonb_build_object(
            'version', 1,
            'pending_generation', v_generation::text,
            'pending_page_count', p_page_count,
            'pending_chunk_count', v_chunk_count,
            'pending_content_sha256', pg_catalog.lower(p_document_sha256),
            'pending_page_mapping', 'one_pdf_page_per_chunk',
            'pending_chunks_written_at', pg_catalog.now()
          ),
        true
      )
  WHERE d.id = p_document_id;

  INSERT INTO rag.audit_events (event_type, document_id, details)
  VALUES (
    'page_aware_generation_staged',
    p_document_id,
    pg_catalog.jsonb_build_object(
      'generation', v_generation::text,
      'document_sha256', pg_catalog.lower(p_document_sha256),
      'page_count', p_page_count,
      'chunk_count', v_chunk_count,
      'page_mapping', 'one_pdf_page_per_chunk',
      'chunk_index_base', v_chunk_base,
      'previous_chunks_retained', true
    )
  );

  RETURN pg_catalog.jsonb_build_object(
    'document_id', p_document_id,
    'generation', v_generation::text,
    'page_count', p_page_count,
    'chunks_appended', v_chunk_count,
    'page_mapped_chunks', v_chunk_count,
    'previous_chunks_retained', true,
    'status', 'processing'
  );
END;
$function$;

REVOKE ALL ON FUNCTION public.rag_worker_stage_document_generation(uuid, integer, jsonb, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.rag_worker_stage_document_generation(uuid, integer, jsonb, text)
  TO service_role;

CREATE OR REPLACE FUNCTION public.rag_worker_list_chunks(
  p_document_id uuid,
  p_only_unembedded boolean DEFAULT true,
  p_limit integer DEFAULT 2000
)
RETURNS TABLE(
  chunk_id uuid,
  document_id uuid,
  chunk_index integer,
  page_start integer,
  page_end integer,
  text_content text,
  token_count integer,
  content_sha256 text,
  embedding_model text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO ''
AS $function$
DECLARE
  v_pending_generation text;
BEGIN
  IF p_document_id IS NULL THEN
    RAISE EXCEPTION 'p_document_id is required' USING ERRCODE = '22023';
  END IF;

  SELECT d.metadata->'page_aware_ingest'->>'pending_generation'
  INTO v_pending_generation
  FROM rag.documents AS d
  WHERE d.id = p_document_id;

  IF v_pending_generation IS NULL THEN
    RAISE EXCEPTION 'No pending page-aware generation exists for document %', p_document_id
      USING ERRCODE = '55000';
  END IF;

  RETURN QUERY
  SELECT c.id, c.document_id, c.chunk_index, c.page_start, c.page_end,
         c.text_content, c.token_count, c.content_sha256, c.embedding_model
  FROM rag.chunks AS c
  WHERE c.document_id = p_document_id
    AND c.metadata->>'ingest_generation' = v_pending_generation
    AND (NOT COALESCE(p_only_unembedded, true) OR c.embedding IS NULL)
  ORDER BY c.chunk_index
  LIMIT LEAST(GREATEST(COALESCE(p_limit, 2000), 1), 10000);
END;
$function$;

CREATE OR REPLACE FUNCTION public.rag_worker_store_embeddings(
  p_items jsonb,
  p_model text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO ''
AS $function$
DECLARE
  v_item jsonb;
  v_expected integer := 0;
  v_updated integer := 0;
  v_stale integer := 0;
  v_rows integer;
  v_activated integer := 0;
  v_touched uuid[] := ARRAY[]::uuid[];
BEGIN
  IF p_model IS NULL OR length(btrim(p_model)) = 0 THEN
    RAISE EXCEPTION 'p_model is required' USING ERRCODE = '22023';
  END IF;
  IF jsonb_typeof(p_items) IS DISTINCT FROM 'array'
     OR jsonb_array_length(p_items) = 0 THEN
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
        embedded_at = pg_catalog.now()
    FROM rag.documents AS d
    WHERE c.id = (v_item->>'chunk_id')::uuid
      AND c.document_id = d.id
      AND c.content_sha256 = v_item->>'content_sha256'
      AND c.page_start IS NOT NULL
      AND c.page_end = c.page_start
      AND c.metadata->>'ingest_generation' =
          (d.metadata->'page_aware_ingest'->>'pending_generation');

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    v_updated := v_updated + v_rows;
    IF v_rows = 0 THEN
      v_stale := v_stale + 1;
    ELSE
      v_touched := pg_catalog.array_append(v_touched, (v_item->>'chunk_id')::uuid);
    END IF;
  END LOOP;

  -- Activate only a complete pending generation. Existing/legacy chunks are ignored
  -- for this gate and remain untouched in the database.
  UPDATE rag.documents AS d
  SET page_count = (d.metadata->'page_aware_ingest'->>'pending_page_count')::integer,
      content_sha256 = pg_catalog.lower(d.metadata->'page_aware_ingest'->>'pending_content_sha256'),
      ingest_status = 'indexed',
      indexed_at = pg_catalog.now(),
      updated_at = pg_catalog.now(),
      ingest_error = NULL,
      metadata = pg_catalog.jsonb_set(
        COALESCE(d.metadata, '{}'::jsonb),
        '{page_aware_ingest}',
        (
          (
            COALESCE(d.metadata->'page_aware_ingest', '{}'::jsonb)
              - 'pending_generation'
              - 'pending_page_count'
              - 'pending_chunk_count'
              - 'pending_content_sha256'
              - 'pending_page_mapping'
              - 'pending_chunks_written_at'
          )
          || pg_catalog.jsonb_build_object(
            'version', 1,
            'active_generation', d.metadata->'page_aware_ingest'->>'pending_generation',
            'page_count', (d.metadata->'page_aware_ingest'->>'pending_page_count')::integer,
            'chunk_count', (d.metadata->'page_aware_ingest'->>'pending_chunk_count')::integer,
            'content_sha256', pg_catalog.lower(d.metadata->'page_aware_ingest'->>'pending_content_sha256'),
            'page_mapping', 'one_pdf_page_per_chunk',
            'indexed_at', pg_catalog.now()
          )
        ),
        true
      )
  WHERE d.id IN (
      SELECT DISTINCT c.document_id
      FROM rag.chunks AS c
      WHERE c.id = ANY(v_touched)
    )
    AND NULLIF(d.metadata->'page_aware_ingest'->>'pending_generation', '') IS NOT NULL
    AND COALESCE((d.metadata->'page_aware_ingest'->>'pending_chunk_count')::integer, -1) > 0
    AND (
      SELECT count(*)::integer
      FROM rag.chunks AS c
      WHERE c.document_id = d.id
        AND c.metadata->>'ingest_generation' =
            (d.metadata->'page_aware_ingest'->>'pending_generation')
    ) = (d.metadata->'page_aware_ingest'->>'pending_chunk_count')::integer
    AND NOT EXISTS (
      SELECT 1
      FROM rag.chunks AS c
      WHERE c.document_id = d.id
        AND c.metadata->>'ingest_generation' =
            (d.metadata->'page_aware_ingest'->>'pending_generation')
        AND (
          c.embedding IS NULL
          OR c.embedding_model IS DISTINCT FROM p_model
          OR c.embedded_at IS NULL
          OR c.page_start IS NULL
          OR c.page_end <> c.page_start
        )
    );

  GET DIAGNOSTICS v_activated = ROW_COUNT;

  RETURN pg_catalog.jsonb_build_object(
    'model', p_model,
    'received', v_expected,
    'stored', v_updated,
    'stale_or_unmapped', v_stale,
    'activated_documents', v_activated,
    'dimensions', 384,
    'previous_chunks_retained', true
  );
END;
$function$;

CREATE OR REPLACE FUNCTION rag.match_chunks_keyword(
  query_text text,
  match_count integer DEFAULT 10,
  min_rank double precision DEFAULT 0
)
RETURNS TABLE(
  chunk_id uuid,
  document_id uuid,
  document_name text,
  source_path text,
  chunk_index integer,
  page_start integer,
  page_end integer,
  text_content text,
  content_sha256 text,
  rank double precision
)
LANGUAGE sql
STABLE
SET search_path TO ''
AS $function$
  WITH q AS (
    SELECT pg_catalog.plainto_tsquery('pg_catalog.simple'::pg_catalog.regconfig, query_text) AS tsq
  )
  SELECT
    c.id AS chunk_id,
    c.document_id,
    d.source_name AS document_name,
    d.source_path,
    c.chunk_index,
    c.page_start,
    c.page_end,
    c.text_content,
    c.content_sha256,
    pg_catalog.ts_rank_cd(c.search_vector, q.tsq)::double precision AS rank
  FROM rag.chunks AS c
  JOIN rag.documents AS d ON d.id = c.document_id
  CROSS JOIN q
  WHERE pg_catalog.numnode(q.tsq) > 0
    AND c.search_vector @@ q.tsq
    AND pg_catalog.ts_rank_cd(c.search_vector, q.tsq) >= min_rank
    AND (
      (
        NULLIF(d.metadata->'page_aware_ingest'->>'active_generation', '') IS NOT NULL
        AND c.metadata->>'ingest_generation' = d.metadata->'page_aware_ingest'->>'active_generation'
      )
      OR
      (
        NULLIF(d.metadata->'page_aware_ingest'->>'active_generation', '') IS NULL
        AND c.metadata->>'ingest_generation' IS NULL
      )
    )
  ORDER BY pg_catalog.ts_rank_cd(c.search_vector, q.tsq) DESC, c.document_id, c.chunk_index
  LIMIT LEAST(GREATEST(COALESCE(match_count, 10), 1), 50);
$function$;

CREATE OR REPLACE FUNCTION rag.match_chunks_semantic(
  query_embedding extensions.vector,
  match_count integer DEFAULT 10,
  min_similarity double precision DEFAULT 0.0
)
RETURNS TABLE(
  chunk_id uuid,
  document_id uuid,
  document_name text,
  source_path text,
  chunk_index integer,
  page_start integer,
  page_end integer,
  text_content text,
  content_sha256 text,
  similarity double precision
)
LANGUAGE sql
STABLE
SET search_path TO ''
AS $function$
  SELECT
    c.id AS chunk_id,
    c.document_id,
    d.source_name AS document_name,
    d.source_path,
    c.chunk_index,
    c.page_start,
    c.page_end,
    c.text_content,
    c.content_sha256,
    (1 - (c.embedding OPERATOR(extensions.<=>) query_embedding))::double precision AS similarity
  FROM rag.chunks AS c
  JOIN rag.documents AS d ON d.id = c.document_id
  WHERE c.embedding IS NOT NULL
    AND (1 - (c.embedding OPERATOR(extensions.<=>) query_embedding)) >= min_similarity
    AND (
      (
        NULLIF(d.metadata->'page_aware_ingest'->>'active_generation', '') IS NOT NULL
        AND c.metadata->>'ingest_generation' = d.metadata->'page_aware_ingest'->>'active_generation'
      )
      OR
      (
        NULLIF(d.metadata->'page_aware_ingest'->>'active_generation', '') IS NULL
        AND c.metadata->>'ingest_generation' IS NULL
      )
    )
  ORDER BY c.embedding OPERATOR(extensions.<=>) query_embedding
  LIMIT LEAST(GREATEST(COALESCE(match_count, 10), 1), 50);
$function$;

-- Retire the old destructive RPC so no caller can accidentally invoke its DELETE path.
DROP FUNCTION IF EXISTS public.rag_worker_replace_document_chunks(uuid, integer, jsonb);

-- Tighten/retain service-only invocation on worker RPCs after replacements.
REVOKE ALL ON FUNCTION public.rag_worker_list_chunks(uuid, boolean, integer)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.rag_worker_list_chunks(uuid, boolean, integer)
  TO service_role;
REVOKE ALL ON FUNCTION public.rag_worker_store_embeddings(jsonb, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.rag_worker_store_embeddings(jsonb, text)
  TO service_role;
REVOKE ALL ON FUNCTION public.rag_worker_match_keyword(text, integer, double precision)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.rag_worker_match_keyword(text, integer, double precision)
  TO service_role;
REVOKE ALL ON FUNCTION public.rag_worker_match_semantic(jsonb, integer, double precision)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.rag_worker_match_semantic(jsonb, integer, double precision)
  TO service_role;
