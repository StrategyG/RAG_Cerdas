# Connect ChatGPT to Institutional RAG

## Current state

- Edge Function: `institutional-rag-search`
- Function URL: `https://uktauwysjkseqrnbjwzy.supabase.co/functions/v1/institutional-rag-search`
- Authentication: custom `x-rag-api-key` header checked in the function. Supabase JWT verification is disabled only because the function validates this separate secret itself; requests without the secret fail closed.
- Retrieval: keyword search through the existing service-role-only `rag_worker_match_keyword` RPC.
- This is not semantic retrieval yet. Search results are returned only when the database retrieval function finds chunks with valid single-page citations.

## Required secret setup (manual)

1. Open the Supabase Dashboard for project `institutional-rag`.
2. Go to **Edge Functions → Secrets**.
3. Add a secret named `RAG_CHATGPT_API_KEY`.
4. Generate a strong random value in a password manager or trusted local generator. Do not paste it into source control, logs, or chat.
5. Save it, then use the exact same value as the custom API key for the ChatGPT Action below.

The function already uses Supabase's server-side `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` environment variables. Never expose the service-role key to ChatGPT.

## Configure a ChatGPT GPT Action

1. In ChatGPT, create or edit a GPT that supports Actions.
2. Add an Action and import `docs/institutional-rag-chatgpt-action.openapi.yaml` from this repository, or paste its contents.
3. Set authentication to **API Key → Custom**.
4. Header name: `x-rag-api-key`.
5. Value: the `RAG_CHATGPT_API_KEY` value you saved in Supabase. Keep the value private.
6. Save and test the action.

If your ChatGPT account does not offer GPT Actions, this endpoint is still deployed but must be connected using a supported remote-app/MCP configuration; do not expose the endpoint publicly as a workaround.

## Request example

```http
POST /functions/v1/institutional-rag-search
Content-Type: application/json
x-rag-api-key: <your-private-key>

{"query":"Ikigai","limit":5}
```

Expected response states:
- `evidence_found`: the service returned citation-safe excerpts; cite the supplied `citation` field and keep claims grounded in the excerpts.
- `no_evidence`: no eligible chunk was returned; do not invent an answer or citation.
- `401`: key missing or invalid.
- `503`: retrieval is unavailable; retry later and inspect function logs without exposing secrets.

## Current corpus limitation

The database currently has legacy `rag` tables with 25,343 chunks but 0 embedded chunks and 0 chunks with verified page mapping; 0 documents are marked indexed. A separate `institutional_rag` catalog has 300 source rows and 5 chunks, also with 0 embeddings. Therefore the Action endpoint can be deployed and authenticated, but it will not return grounded evidence until the ingestion pipeline is run and verified.

The existing page-aware ingestion worker uses `rag_pipeline.py`, the `intfloat/multilingual-e5-small` model (384 dimensions), and Dropbox source access. Run the pilot from the repository's documented Codespaces workflow before a full corpus run. Keep source PDFs unchanged; ingestion should append a new page-aware generation and preserve prior chunks.

## Acceptance checks

- [ ] `RAG_CHATGPT_API_KEY` exists in Supabase Edge Function secrets.
- [ ] Missing/wrong key returns HTTP 401.
- [ ] Correct key GET returns `status: reachable`.
- [ ] Correct key POST returns a valid JSON response.
- [ ] After ingestion, results have valid document title and one-based page citation.
- [ ] Ask ChatGPT a question whose answer is in a known PDF; confirm the action is called and each source-grounded claim cites a returned page.
- [ ] Ask a question absent from the indexed corpus; confirm ChatGPT reports insufficient RAG evidence rather than fabricating citations.
