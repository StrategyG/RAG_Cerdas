# WhatsApp AI Agent Pilot (semi-automatic)

## Scope
This is an additive pilot for `StrategyG/RAG_Cerdas`. It does not alter existing RAG tables or automatically send AI-generated text. Incoming text messages are stored for review; a human must explicitly submit an approved reply to the `/approve` route.

## Current implementation boundary
- Meta webhook GET verification using `WHATSAPP_VERIFY_TOKEN`.
- POST webhook signature validation using HMAC-SHA256 and `META_APP_SECRET`.
- Inbound text-message persistence with provider message ID deduplication.
- Explicit reply endpoint protected by `WHATSAPP_APPROVAL_SECRET`.
- Sends only the exact `approved_reply` supplied by the operator.
- AI draft generation, dashboard UI, audio/media handling, outbound templates, and automatic follow-up are intentionally not enabled.

## Required server-side secrets
Set these in Supabase Edge Function secrets (never in Git, client-side code, or chat):
- `META_APP_SECRET`
- `WHATSAPP_VERIFY_TOKEN` (choose a long random value)
- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_APPROVAL_SECRET` (choose a different long random value)
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` (if required by the project's runtime; never expose publicly)
- Optional `META_GRAPH_API_VERSION` (defaults to `v23.0`)

## Safe deployment sequence
1. Review this migration and function on a feature branch.
2. Apply `supabase/migrations/20261020130000_whatsapp_inbox.sql` only after approval.
3. Set secrets in Supabase Dashboard > Edge Functions > Secrets.
4. Deploy the function as `whatsapp-gateway`.
5. Configure the Meta app webhook callback URL to the deployed function URL and subscribe to the `messages` field.
6. Run Meta's webhook verification and signed test-event checks before using a real customer number.
7. Keep AI draft generation disconnected until the RAG retrieval interface and human approval UI are verified.

## Operator approval call
Send a POST request to `<function-url>/approve` with header `x-approval-secret: <secret>` and JSON:
```json
{
  "message_id": "<Meta inbound message ID>",
  "approved_reply": "<human-reviewed reply>"
}
```
Never put the approval secret in a browser frontend or commit it. Call this endpoint only from a trusted operator-side backend or a private admin tool.

## Acceptance criteria
- Invalid/missing Meta signature returns 401.
- Valid GET subscription verification returns the exact challenge.
- Duplicate inbound message IDs do not create duplicate inbox rows.
- Non-text events are safely ignored.
- Missing/invalid approval secret returns 401.
- Reply is sent only through explicit approval action.
- Database table is inaccessible to `anon` and `authenticated` roles.
- No tokens or message bodies are emitted to logs.
- A real end-to-end test must be recorded separately; code presence is not proof of connectivity.
