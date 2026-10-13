# Mikumiku Matchup Lab — Reg MC / Supabase persistent edition

Python + Streamlit app for collecting public Pokémon Showdown replays and reviewing matchup trends for `mikumiku37` and `mikumiku38`, restricted to `gen9championsvgc2026regmc`.

## 1. Create Supabase database

1. Create a project at https://supabase.com/
2. Open **SQL Editor** in the project dashboard.
3. Paste and run the contents of `supabase_schema.sql`.
4. In Project Settings / API (or Connect, depending on dashboard UI), copy:
   - Project URL
   - server-side secret/service-role key

Do not put the key in `app.py`, `requirements.txt`, or any GitHub file.

## 2. Upload files to a Public GitHub repository

Upload these files to the repository root:
- `app.py`
- `requirements.txt`
- `README.md`
- `supabase_schema.sql`

Never upload Streamlit secrets or database credentials.

## 3. Deploy to Streamlit Community Cloud

1. Visit https://share.streamlit.io/
2. Sign in with GitHub and deploy the repository.
3. Main file path: `app.py`.
4. In app settings, open **Secrets** and add:

```toml
SUPABASE_URL = "https://YOUR_PROJECT_REF.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "YOUR_SERVER_SIDE_SECRET_KEY"
```

Use the server-side secret/service-role key only in Streamlit Secrets. Never put it in GitHub or share screenshots that show it. If the dashboard offers a newer `sb_secret_...` key, use that server-side key; do not use a publishable/anon key unless the database policies are specifically configured for it.

5. Save secrets and reboot/redeploy the app.

## 4. Persistent storage

Replay records are stored in Supabase PostgreSQL, not in the app's local filesystem. App restarts/redeploys should not delete those rows. Back up the Supabase project periodically.

## 5. Run locally (optional)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

For local run, create `.streamlit/secrets.toml` with the same two values. Do not commit this file. Add `.streamlit/secrets.toml` to `.gitignore`.

## Data limitations

- Search only returns public/available replay data.
- Team grouping is based on the six species in team preview; it cannot reliably distinguish different move/item/ability/Tera sets.
- Pokémon that never entered the field may be impossible to recover as selected. The app labels these as observed entries, not confirmed full selections.
- Closed-sheet and OTS are currently analysis labels/filters, not a complete pre-battle-information reconstruction engine.


## Improvement patch notes
- Explicit CRUD grants for `service_role` address `permission denied for table replays`.
- Better diagnostics for permission, missing-table, and invalid-key errors.
- Replay records with a non-Reg M-C actual format are skipped.
- Invalid upload timestamps no longer interrupt collection.
- Sidebar shows DB connection status and loaded row count.
- Closed/OTS is clearly documented as a label only; replay logs cannot fully reconstruct pre-battle information.
