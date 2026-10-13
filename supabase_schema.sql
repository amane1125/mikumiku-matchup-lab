-- Safe to re-run. Does not delete existing replay data.
create table if not exists public.replays (
    replay_id text primary key, replay_url text, format_id text, uploadtime bigint,
    rating integer, p1 text, p2 text, winner text, p1_team text, p2_team text,
    p1_selected text, p2_selected text, p1_leads text, p2_leads text,
    selection_confidence text, log_text text, fetched_at timestamptz
);
create index if not exists replays_format_id_idx on public.replays (format_id);
create index if not exists replays_uploadtime_idx on public.replays (uploadtime desc);
alter table public.replays enable row level security;
grant select, insert, update, delete on table public.replays to service_role;
