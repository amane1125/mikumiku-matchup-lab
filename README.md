# Mikumiku Matchup Lab (v0.1)

Python + Streamlit app for collecting public Pokémon Showdown replays and reviewing matchup/observed lead trends for mikumiku37 and mikumiku38.

## Run

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

Open the local URL shown by Streamlit.

## Defaults

- Users: `mikumiku37`, `mikumiku38`
- Format ID: `gen9championsvgc2026regmc`

This version is locked to Regulation M-C (`gen9championsvgc2026regmc`) so other regulations are not mixed into the analysis.

## Data behavior / limitations

- Uses the public Replay API: `/search.json` and `/{replay_id}.json`.
- Data is stored in `mikumiku_lab.sqlite3` beside `app.py`.
- Team grouping is based on the six species in the team preview. It cannot reliably separate different moves/items/abilities/Tera sets for the same six species.
- Replay logs show Pokémon that entered the field, not necessarily all four selected Pokémon. The app labels these as observed entries, not confirmed full selections.
- Closed-sheet analysis must not use information that was revealed only during/after the battle. This version deliberately does not infer hidden moves/items/abilities; a strict time-of-information OTS data model is planned for the next version.
- Public replay search cannot retrieve private or unsaved battles.

## Suggested next improvements

1. Explicit team registry with labels and imported Showdown paste/team exports.
2. Separate pre-battle OTS data from battle log revelations.
3. Replay parser tests against real replay variants.
4. Per-opponent six-species matchup summaries and exact selection labels when the log makes them available.
5. Manual corrections for team identity, selected four, and leads.
