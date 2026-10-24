alter table institutional_rag.document_chunks
  add column if not exists search_vector tsvector
  generated always as (to_tsvector('simple', coalesce(content, ''))) stored;

create index if not exists document_chunks_search_vector_gin
  on institutional_rag.document_chunks using gin(search_vector);

create or replace function institutional_rag.search_chunks(
  query_text text,
  result_limit integer default 10
)
returns table (
  chunk_id uuid,
  source_document_id uuid,
  title text,
  source_path text,
  content text,
  page_start integer,
  page_end integer,
  rank real
)
language sql
stable
security invoker
set search_path = institutional_rag, pg_temp
as $$
  select c.id, d.id, d.title, d.source_path, c.content, c.page_start, c.page_end,
         ts_rank(c.search_vector, websearch_to_tsquery('simple', query_text)) as rank
  from institutional_rag.document_chunks c
  join institutional_rag.source_documents d on d.id = c.source_document_id
  where nullif(trim(query_text), '') is not null
    and c.search_vector @@ websearch_to_tsquery('simple', query_text)
  order by rank desc
  limit greatest(1, least(coalesce(result_limit, 10), 100));
$$;

revoke all on function institutional_rag.search_chunks(text, integer) from public, anon, authenticated;
grant execute on function institutional_rag.search_chunks(text, integer) to service_role;

create or replace view institutional_rag.system_status as
select
  (select count(*) from institutional_rag.source_documents) as registered_documents,
  (select count(*) from institutional_rag.source_documents where status = 'indexed') as indexed_documents,
  (select count(*) from institutional_rag.document_chunks) as chunks,
  (select count(*) from institutional_rag.document_chunks where embedding is not null) as embedded_chunks,
  (select count(*) from institutional_rag.ingestion_runs) as ingestion_runs,
  (select count(*) from institutional_rag.evaluation_cases where active) as active_evaluation_cases,
  (select count(*) from institutional_rag.evaluation_results) as evaluation_results;
revoke all on institutional_rag.system_status from public, anon, authenticated;
grant select on institutional_rag.system_status to service_role;
