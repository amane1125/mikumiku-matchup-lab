-- Mikumiku Matchup Lab: Supabase schema
-- Run this script in Supabase Dashboard > SQL Editor.
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

alter table public.replays enable row level security;

-- The app uses the server-side service role key from Streamlit Secrets.
-- Never expose this key in client-side code or commit it to GitHub.
grant select, insert, update, delete on table public.replays to service_role;
