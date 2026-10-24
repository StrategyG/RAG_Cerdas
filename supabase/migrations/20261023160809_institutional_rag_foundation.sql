create schema if not exists institutional_rag;
revoke all on schema institutional_rag from public, anon, authenticated;
grant usage on schema institutional_rag to service_role;

create table if not exists institutional_rag.source_documents (
  id uuid primary key default gen_random_uuid(),
  provider text not null default 'dropbox',
  source_id text not null,
  source_path text not null,
  title text not null,
  mime_type text,
  file_size_bytes bigint check (file_size_bytes is null or file_size_bytes >= 0),
  source_modified_at timestamptz,
  content_sha256 text,
  status text not null default 'discovered'
    check (status in ('discovered','queued','extracting','extracted','chunked','embedded','indexed','failed','skipped')),
  page_count integer check (page_count is null or page_count >= 0),
  last_ingested_at timestamptz,
  error_message text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (provider, source_id)
);

create table if not exists institutional_rag.document_chunks (
  id uuid primary key default gen_random_uuid(),
  source_document_id uuid not null references institutional_rag.source_documents(id) on delete restrict,
  chunk_index integer not null check (chunk_index >= 0),
  content text not null,
  page_start integer check (page_start is null or page_start >= 1),
  page_end integer check (page_end is null or page_end >= 1),
  token_count integer check (token_count is null or token_count >= 0),
  embedding vector,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (source_document_id, chunk_index),
  check (page_start is null or page_end is null or page_end >= page_start)
);

create table if not exists institutional_rag.ingestion_runs (
  id uuid primary key default gen_random_uuid(),
  run_type text not null default 'full_scan'
    check (run_type in ('full_scan','incremental','single_file','reprocess','evaluation')),
  status text not null default 'queued'
    check (status in ('queued','running','completed','completed_with_errors','failed','cancelled')),
  started_at timestamptz,
  finished_at timestamptz,
  files_discovered integer not null default 0 check (files_discovered >= 0),
  files_processed integer not null default 0 check (files_processed >= 0),
  files_failed integer not null default 0 check (files_failed >= 0),
  chunks_created integer not null default 0 check (chunks_created >= 0),
  embeddings_created integer not null default 0 check (embeddings_created >= 0),
  report jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists institutional_rag.evaluation_cases (
  id uuid primary key default gen_random_uuid(),
  case_key text not null unique,
  question text not null,
  expected_source_ids text[] not null default '{}',
  expected_pages integer[] not null default '{}',
  expected_answer_notes text,
  active boolean not null default true,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists institutional_rag.evaluation_results (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references institutional_rag.ingestion_runs(id) on delete restrict,
  case_id uuid references institutional_rag.evaluation_cases(id) on delete restrict,
  retrieved_chunk_ids uuid[] not null default '{}',
  citation_accuracy numeric check (citation_accuracy is null or citation_accuracy between 0 and 1),
  retrieval_relevance numeric check (retrieval_relevance is null or retrieval_relevance between 0 and 1),
  answer_grounded boolean,
  notes text,
  metrics jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists source_documents_status_idx on institutional_rag.source_documents(status);
create index if not exists source_documents_modified_idx on institutional_rag.source_documents(source_modified_at desc);
create index if not exists document_chunks_source_idx on institutional_rag.document_chunks(source_document_id, chunk_index);
create index if not exists ingestion_runs_created_idx on institutional_rag.ingestion_runs(created_at desc);
create index if not exists evaluation_results_run_idx on institutional_rag.evaluation_results(run_id);

alter table institutional_rag.source_documents enable row level security;
alter table institutional_rag.document_chunks enable row level security;
alter table institutional_rag.ingestion_runs enable row level security;
alter table institutional_rag.evaluation_cases enable row level security;
alter table institutional_rag.evaluation_results enable row level security;

revoke all on all tables in schema institutional_rag from public, anon, authenticated;
grant select, insert, update, delete on all tables in schema institutional_rag to service_role;
