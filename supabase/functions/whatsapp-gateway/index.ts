// WhatsApp Business webhook gateway (pilot).
// Never logs message text or access tokens. Replies require explicit operator approval.
const corsHeaders = {
  "Access-Control-Allow-Origin": "https://github.com",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, x-approval-secret, x-hub-signature-256",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });

const env = (name: string) => Deno.env.get(name) ?? "";

async function verifyMetaSignature(rawBody: string, signature: string): Promise<boolean> {
  const secret = env("META_APP_SECRET");
  if (!secret || !signature.startsWith("sha256=")) return false;
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(rawBody)));
  const expected = "sha256=" + Array.from(mac, (b) => b.toString(16).padStart(2, "0")).join("");
  if (expected.length !== signature.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) diff |= expected.charCodeAt(i) ^ signature.charCodeAt(i);
  return diff === 0;
}

async function dbRequest(path: string, method: string, body?: unknown, prefer = "return=representation") {
  const url = env("SUPABASE_URL");
  const key = env("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !key) throw new Error("Server database configuration is incomplete");
  return await fetch(`${url}/rest/v1/${path}`, {
    method,
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      Prefer: prefer,
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

async function handleWebhook(req: Request): Promise<Response> {
  const url = new URL(req.url);
  if (req.method === "GET") {
    const mode = url.searchParams.get("hub.mode");
    const token = url.searchParams.get("hub.verify_token");
    const challenge = url.searchParams.get("hub.challenge");
    if (mode === "subscribe" && token && token === env("WHATSAPP_VERIFY_TOKEN") && challenge) {
      return new Response(challenge, { status: 200, headers: corsHeaders });
    }
    return json({ error: "Webhook verification failed" }, 403);
  }
  if (req.method !== "POST") return json({ error: "Method not allowed" }, 405);

  const rawBody = await req.text();
  const signature = req.headers.get("x-hub-signature-256") ?? "";
  if (!(await verifyMetaSignature(rawBody, signature))) {
    return json({ error: "Invalid webhook signature" }, 401);
  }

  let payload: any;
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return json({ error: "Invalid JSON" }, 400);
  }

  const rows: Record<string, unknown>[] = [];
  for (const entry of payload.entry ?? []) {
    for (const change of entry.changes ?? []) {
      if (change.field !== "messages") continue;
      const value = change.value ?? {};
      const phoneNumberId = value.metadata?.phone_number_id ?? null;
      for (const message of value.messages ?? []) {
        if (message.type !== "text" || !message.id || !message.from) continue;
        const timestamp = Number(message.timestamp);
        rows.push({
          provider: "whatsapp",
          provider_message_id: String(message.id),
          sender_wa_id: String(message.from),
          phone_number_id: phoneNumberId,
          message_text: String(message.text?.body ?? "").slice(0, 10000),
          status: "needs_review",
          received_at: Number.isFinite(timestamp) && timestamp > 0
            ? new Date(timestamp * 1000).toISOString()
            : new Date().toISOString(),
          metadata: { message_type: message.type },
        });
      }
    }
  }

  // PostgREST upsert makes webhook retries idempotent for provider_message_id.
  if (rows.length) {
    const response = await dbRequest(
      "whatsapp_inbox?on_conflict=provider_message_id",
      "POST",
      rows,
      "resolution=ignore-duplicates,return=minimal",
    );
    if (!response.ok) return json({ error: "Could not persist inbound event" }, 500);
  }
  return json({ received: true, stored: rows.length });
}

async function approveAndSend(req: Request): Promise<Response> {
  const supplied = req.headers.get("x-approval-secret") ?? "";
  const approvalSecret = env("WHATSAPP_APPROVAL_SECRET");
  if (!approvalSecret || supplied.length !== approvalSecret.length) return json({ error: "Unauthorized" }, 401);
  let mismatch = 0;
  for (let i = 0; i < supplied.length; i++) mismatch |= supplied.charCodeAt(i) ^ approvalSecret.charCodeAt(i);
  if (mismatch !== 0) return json({ error: "Unauthorized" }, 401);

  let body: any;
  try {
    body = await req.json();
  } catch {
    return json({ error: "Invalid JSON" }, 400);
  }
  const messageId = String(body.message_id ?? "");
  const reply = String(body.approved_reply ?? "").trim();
  if (!messageId || !reply || reply.length > 4096) {
    return json({ error: "message_id and approved_reply (1-4096 chars) are required" }, 400);
  }

  // Atomically claim only a message that has not already been claimed or sent.
  const lookup = await dbRequest(
    `whatsapp_inbox?provider_message_id=eq.${encodeURIComponent(messageId)}&status=in.(needs_review,draft_ready)&select=provider_message_id,sender_wa_id,phone_number_id,status`,
    "PATCH",
    { status: "sending" },
    "return=representation",
  );
  if (!lookup.ok) return json({ error: "Could not claim inbox record" }, 500);
  const records = await lookup.json();
  const record = records?.[0];
  if (!record) return json({ error: "Message not found, already claimed, or already replied to" }, 409);

  const token = env("WHATSAPP_ACCESS_TOKEN");
  const phoneId = String(record.phone_number_id || env("WHATSAPP_PHONE_NUMBER_ID"));
  const graphVersion = env("META_GRAPH_API_VERSION") || "v23.0";
  if (!token || !phoneId || !record.sender_wa_id) {
    await dbRequest(`whatsapp_inbox?provider_message_id=eq.${encodeURIComponent(messageId)}&status=eq.sending`, "PATCH", { status: "failed" });
    return json({ error: "WhatsApp sending configuration is incomplete" }, 503);
  }

  let sendResponse: Response;
  let sendResult: any;
  try {
    sendResponse = await fetch(`https://graph.facebook.com/${graphVersion}/${phoneId}/messages`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        messaging_product: "whatsapp",
        recipient_type: "individual",
        to: record.sender_wa_id,
        type: "text",
        text: { preview_url: false, body: reply },
      }),
    });
    sendResult = await sendResponse.json().catch(() => ({}));
  } catch {
    await dbRequest(`whatsapp_inbox?provider_message_id=eq.${encodeURIComponent(messageId)}&status=eq.sending`, "PATCH", { status: "failed" });
    return json({ error: "WhatsApp API request failed; verify delivery status before retrying" }, 502);
  }
  if (!sendResponse.ok) {
    await dbRequest(`whatsapp_inbox?provider_message_id=eq.${encodeURIComponent(messageId)}&status=eq.sending`, "PATCH", { status: "failed" });
    return json({ error: "WhatsApp API rejected the approved reply" }, 502);
  }

  const update = await dbRequest(
    `whatsapp_inbox?provider_message_id=eq.${encodeURIComponent(messageId)}&status=eq.sending`,
    "PATCH",
    { status: "sent", approved_reply: reply, sent_at: new Date().toISOString(), outbound_message_id: sendResult.messages?.[0]?.id ?? null },
  );
  if (!update.ok) return json({ error: "Reply sent but inbox status update failed; check Meta message status before retrying" }, 502);
  return json({ sent: true, outbound_message_id: sendResult.messages?.[0]?.id ?? null });
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  const path = new URL(req.url).pathname.replace(/\/$/, "");
  try {
    if (path.endsWith("/approve")) {
      if (req.method !== "POST") return json({ error: "Method not allowed" }, 405);
      return await approveAndSend(req);
    }
    return await handleWebhook(req);
  } catch {
    return json({ error: "Internal gateway error" }, 500);
  }
});
