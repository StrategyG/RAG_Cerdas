-- Additive lexical index for the private IM19 retrieval path.
-- The indexed expression exactly matches im19.retrieval.HybridRetriever.
-- Apply to a backup-restored staging database first; never auto-apply at worker startup.
-- The simple configuration avoids language-specific stemming and retains multilingual terms.
BEGIN;

CREATE INDEX IF NOT EXISTS chunks_text_search_gin_idx
ON im19.chunks USING gin (
  pg_catalog.to_tsvector(
    'pg_catalog.simple'::pg_catalog.regconfig,
    text_content
  )
);

COMMENT ON INDEX im19.chunks_text_search_gin_idx IS
  'GIN lexical candidate index for IM19 hybrid retrieval; not a BM25 index.';

COMMIT;
