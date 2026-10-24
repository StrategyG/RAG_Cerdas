ALTER TABLE rag.chunks
    ADD COLUMN IF NOT EXISTS embedding extensions.vector(384),
    ADD COLUMN IF NOT EXISTS embedding_model text,
    ADD COLUMN IF NOT EXISTS embedded_at timestamptz;
