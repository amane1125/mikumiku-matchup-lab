# Mikumiku Matchup Lab

## Deploy / setup

1. Commit `app.py` and `requirements.txt` to the GitHub repository connected to Streamlit Community Cloud.
2. In Supabase, open **SQL Editor** and run `supabase_schema.sql`.
3. In Streamlit Community Cloud, open **App settings → Secrets** and set:

```toml
SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "YOUR_SERVICE_ROLE_KEY"
```

Use the **service_role** key only in server-side Streamlit Secrets. Never commit it to the repository or expose it in a browser.
4. Restart/reboot the Streamlit app.

## Behavior

- Format is fixed to `gen9championsvgc2026regmc` (Regulation M-C).
- `mikumiku37` and `mikumiku38` are collected and analyzed together.
- `replay_id` is the primary key, so a replay found through both accounts is counted only once.
- Data is stored in Supabase, not the Streamlit instance's ephemeral local filesystem.
- Team selection is inferred from species observed entering battle; it is not guaranteed to reproduce the exact bring-4 selection.
