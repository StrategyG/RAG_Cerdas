create schema if not exists rag;

create table if not exists rag.documents (
  id uuid primary key default gen_random_uuid(),
  source_provider text not null default 'dropbox',
  source_path text not null,
  source_name text not null,
  content_sha256 text,
  mime_type text,
  file_size_bytes bigint,
  page_count integer,
  ingest_status text not null default 'discovered'
    check (ingest_status in ('discovered','queued','processing','indexed','failed','skipped')),
  ingest_error text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  indexed_at timestamptz,
  unique (source_provider, source_path)
);

create index if not exists documents_status_idx on rag.documents (ingest_status);
create index if not exists documents_hash_idx on rag.documents (content_sha256);

create table if not exists rag.chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references rag.documents(id) on delete cascade,
  chunk_index integer not null,
  page_start integer,
  page_end integer,
  text_content text not null,
  token_count integer,
  content_sha256 text,
  qdrant_point_id uuid not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (document_id, chunk_index),
  unique (qdrant_point_id),
  check (page_start is null or page_start >= 1),
  check (page_end is null or page_end >= 1),
  check (page_start is null or page_end is null or page_end >= page_start)
);

create index if not exists chunks_document_idx on rag.chunks (document_id);
create index if not exists chunks_page_idx on rag.chunks (document_id, page_start, page_end);

create table if not exists rag.ingest_jobs (
  id uuid primary key default gen_random_uuid(),
  document_id uuid references rag.documents(id) on delete set null,
  job_type text not null default 'ingest',
  status text not null default 'queued'
    check (status in ('queued','running','succeeded','failed','cancelled')),
  attempt_count integer not null default 0,
  started_at timestamptz,
  finished_at timestamptz,
  error_message text,
  stats jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists ingest_jobs_status_created_idx on rag.ingest_jobs (status, created_at);

create table if not exists rag.audit_events (
  id bigint generated always as identity primary key,
  event_type text not null,
  document_id uuid references rag.documents(id) on delete set null,
  job_id uuid references rag.ingest_jobs(id) on delete set null,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists audit_events_created_idx on rag.audit_events (created_at desc);
create index if not exists audit_events_type_idx on rag.audit_events (event_type);

revoke all on schema rag from public, anon, authenticated;
revoke all on all tables in schema rag from public, anon, authenticated;
alter default privileges in schema rag revoke all on tables from public, anon, authenticated;
