-- Mikumiku Matchup Lab: per-team strategy notes
-- Run this AFTER the existing supabase_schema.sql in Supabase Dashboard > SQL Editor.
-- Safe to run more than once.
create table if not exists public.strategy_notes (
    id uuid primary key default gen_random_uuid(),
    title text not null,
    our_team_key text not null,
    our_team_species jsonb not null default '[]'::jsonb,
    opponent_team jsonb not null default '[]'::jsonb,
    lead_plan text not null default '',
    opening_plan text not null default '',
    threats text not null default '',
    conditions text not null default '',
    result text not null default '未対戦'
        check (result in ('未対戦', '勝ち', '負け', '引き分け')),
    actual_leads jsonb not null default '[]'::jsonb,
    review text not null default '',
    next_action text not null default '',
    replay_id text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists strategy_notes_our_team_key_idx
    on public.strategy_notes (our_team_key);
create index if not exists strategy_notes_result_idx
    on public.strategy_notes (result);
create index if not exists strategy_notes_updated_at_idx
    on public.strategy_notes (updated_at desc);

create or replace function public.set_strategy_notes_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists strategy_notes_updated_at_trigger on public.strategy_notes;
create trigger strategy_notes_updated_at_trigger
before update on public.strategy_notes
for each row execute function public.set_strategy_notes_updated_at();

alter table public.strategy_notes enable row level security;
grant select, insert, update, delete on table public.strategy_notes to service_role;
