-- Additive migration for the WhatsApp AI-agent pilot.
-- Does not modify or delete existing RAG data.
create table if not exists public.whatsapp_inbox (
  id uuid primary key default gen_random_uuid(),
  provider text not null default 'whatsapp' check (provider = 'whatsapp'),
  provider_message_id text not null unique,
  sender_wa_id text not null,
  phone_number_id text,
  message_text text not null default '',
  status text not null default 'needs_review'
    check (status in ('needs_review', 'draft_ready', 'sending', 'sent', 'failed')),
  approved_reply text,
  outbound_message_id text,
  received_at timestamptz not null default now(),
  sent_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

alter table public.whatsapp_inbox enable row level security;
revoke all on table public.whatsapp_inbox from anon, authenticated;
grant all on table public.whatsapp_inbox to service_role;

create index if not exists whatsapp_inbox_status_received_idx
  on public.whatsapp_inbox (status, received_at desc);
