CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
ON rag.chunks
USING hnsw (embedding extensions.vector_cosine_ops)
WHERE embedding IS NOT NULL;
