# Mikumiku Matchup Lab — Strategy Notes update

## Contents
- `app.py`: Existing replay dashboard plus per-team strategy notes (create, search, edit, delete)
- `supabase_strategy_notes.sql`: Adds the `strategy_notes` table without replacing `replays`
- `requirements.txt`: Python dependencies

## Deploy
1. Back up the current GitHub `app.py`.
2. In Supabase Dashboard → SQL Editor, run the existing `supabase_schema.sql` if not already installed.
3. Run `supabase_strategy_notes.sql` in SQL Editor.
4. Replace the repository `app.py` and `requirements.txt` with these files and commit.
5. Keep Streamlit Secrets configured as `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.
6. Restart/reboot the Streamlit app.

## Notes
- Existing `replays` data is not deleted or migrated.
- Use the sidebar `ページ` selector to switch between `分析ダッシュボード` and `対策ノート`.
- Strategy notes are stored per own-team species key. Team identity is based on species only; it does not distinguish items, moves, abilities, or Tera types.
- `service_role` key must only be stored in Streamlit Secrets and must never be exposed in client-side code or committed to GitHub.
