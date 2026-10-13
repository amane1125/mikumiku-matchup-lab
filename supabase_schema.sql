-- Mikumiku Matchup Lab: run this once in Supabase SQL Editor.
-- Dashboard -> SQL Editor -> New query -> paste -> Run

create table if not exists public.replays (
    replay_id text primary key,
    replay_url text,
    format_id text,
    uploadtime bigint,
    rating integer,
    p1 text,
    p2 text,
    winner text,
    p1_team text,
    p2_team text,
    p1_selected text,
    p2_selected text,
    p1_leads text,
    p2_leads text,
    selection_confidence text,
    log_text text,
    fetched_at timestamptz
);

create index if not exists replays_format_id_idx on public.replays (format_id);
create index if not exists replays_uploadtime_idx on public.replays (uploadtime desc);

-- This app uses a server-side service-role/secret key stored in Streamlit Secrets.
-- Do not expose that key in the browser or commit it to GitHub.
-- Keep RLS enabled; the server-side service key bypasses RLS.
alter table public.replays enable row level security;
