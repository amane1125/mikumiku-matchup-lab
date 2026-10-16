"""
Mikumiku Matchup Lab
Pokémon Showdown 公開リプレイ収集・構築別選出研究ツール
保存先: Supabase (Streamlit Community Cloud対応)
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from datetime import datetime
from typing import Any

import pandas as pd
import requests
import streamlit as st
from supabase import Client, create_client

DEFAULT_FORMAT = "gen9championsvgc2026regmc"
DEFAULT_BOTS = ["mikumiku37", "mikumiku38"]
API_ROOT = "https://replay.pokemonshowdown.com"
HTTP_HEADERS = {
    "User-Agent": "Mikumiku-Matchup-Lab/1.0 (public replay research)"
}

@st.cache_resource
def get_supabase() -> Client:
    """Create a cached Supabase client from Streamlit secrets."""
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
    except Exception as exc:
        raise RuntimeError(
            "Supabaseの接続設定がありません。Streamlit Secretsに "
            "SUPABASE_URL と SUPABASE_SERVICE_ROLE_KEY を設定してください。"
        ) from exc
    if not url or not key:
        raise RuntimeError(
            "Supabaseの接続設定が空です。SUPABASE_URL と "
            "SUPABASE_SERVICE_ROLE_KEY を確認してください。"
        )
    return create_client(str(url), str(key))


def init_db() -> None:
    """Verify that the Supabase table is reachable; schema is managed in Supabase."""
    try:
        get_supabase().table("replays").select("replay_id").limit(1).execute()
    except Exception as exc:
        raise RuntimeError(
            "Supabaseの public.replays テーブルに接続できません。"
            "同梱の supabase_schema.sql をSQL Editorで実行し、Secretsを確認してください。"
            f" 詳細: {exc}"
        ) from exc


def fetch_json(url: str, params: dict | None = None, timeout: int = 25) -> Any:
    response = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.json()


def normalize_user(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def species_from_details(details: str) -> str:
    # Pokémon Showdown details look like "Incineroar, L50, M"
    first = (details or "").split(",", 1)[0].strip()
    first = re.sub(r"\s*\(.*?\)", "", first)
    return first


def selection_species_key(species: str) -> str:
    """Collapse Mega/form labels to the underlying species for distinct bring counts."""
    name = re.sub(r"\s+", "-", (species or "").strip().lower())
    name = name.replace("’", "").replace("'", "")
    # Showdown may report a Mega form as Species-Mega, Species-Mega-X/Y,
    # or a form label such as Floette-Mega / Floette-Eternal.
    name = re.sub(r"-(?:mega(?:-[xy])?|eternal)$", "", name)
    name = re.sub(r"^mega-", "", name)
    return name

def species_sprite_slug(species: str) -> str:
    """Convert a displayed species name to a Pokémon Showdown dex-sprite filename."""
    name = (species or "").strip().lower()
    name = name.replace("♀", "-f").replace("♂", "-m")
    name = name.replace("’", "").replace("'", "")
    name = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    aliases = {
        "nidoran-f": "nidoran-f",
        "nidoran-m": "nidoran-m",
        "mr-mime": "mr-mime",
        "mime-jr": "mime-jr",
        "type-null": "type-null",
        "jangmo-o": "jangmo-o",
        "hakamo-o": "hakamo-o",
        "kommo-o": "kommoo",
        "farfetchd": "farfetchd",
        "sirfetchd": "sirfetchd",
        "flabebe": "flabebe",
    }
    return aliases.get(name, name)


def render_species_icons(species: list[str], *, max_items: int = 6, size: int = 40) -> None:
    """Render small pixel-style sprites in a compact row for mobile screens."""
    names = []
    for value in species or []:
        name = str(value).strip()
        if name and name not in names:
            names.append(name)
    names = names[:max_items]
    if not names:
        st.caption("ポケモン情報なし")
        return

    # Pokémon Showdown's Gen 5 sprites are small pixel-art images.
    # st.image(list) keeps them together in one compact horizontal strip.
    sprite_urls = [
        f"https://play.pokemonshowdown.com/sprites/gen5/{species_sprite_slug(name)}.png"
        for name in names
    ]
    st.image(sprite_urls, width=size)
    st.caption(" · ".join(names))


def parse_log(log_text: str, p1: str = "", p2: str = "") -> dict:
    """Extract only facts visible in the public battle log.
    Selected teams are conservative: the first four distinct species that enter.
    This is explicitly an inference, not guaranteed full selection data.
    """
    players = {"p1": p1, "p2": p2}
    teams = {"p1": [], "p2": []}
    entered = {"p1": [], "p2": []}
    winner = None
    active_turn = 0

    for line in (log_text or "").splitlines():
        parts = line.split("|")
        if len(parts) < 3:
            continue
        tag = parts[1]
        if tag == "player" and len(parts) >= 4:
            players[parts[2]] = parts[3]
        elif tag == "poke" and len(parts) >= 4:
            side = parts[2]
            if side in teams:
                species = species_from_details(parts[3])
                if species and species not in teams[side]:
                    teams[side].append(species)
        elif tag in ("switch", "drag", "replace") and len(parts) >= 4:
            # Doubles logs identify active slots as p1a/p1b/p2a/p2b.
            # Normalize the slot identifier to its owning player (p1/p2).
            slot = parts[2].split(":", 1)[0].strip().lower()
            match = re.match(r"^(p[12])(?:[a-z])?$", slot)
            side = match.group(1) if match else None
            if side in entered:
                species = species_from_details(parts[3])
                # A Mega Evolution is the same selected Pokémon, not a new slot.
                # Compare canonical species keys so a form change cannot inflate bring-4.
                existing_keys = {selection_species_key(value) for value in entered[side]}
                if species and selection_species_key(species) not in existing_keys:
                    entered[side].append(species)
        elif tag == "turn" and len(parts) >= 3:
            try:
                active_turn = int(parts[2])
            except ValueError:
                pass
        elif tag == "win" and len(parts) >= 3:
            winner = parts[2].strip()

    # A few replay variants don't include |poke| lines; fall back to switch sightings.
    for side in ("p1", "p2"):
        if not teams[side]:
            teams[side] = list(entered[side])

    selected = {}
    leads = {}
    confidence = {}
    for side in ("p1", "p2"):
        observed = entered[side]
        # In doubles, only the first two distinct entries are reliable as initial leads.
        leads[side] = observed[:2]
        # Four distinct entries are a lower-bound observation, not always the full bring-4.
        selected[side] = observed[:4]
        confidence[side] = (
            "observed_entries_only" if len(observed) >= 4
            else "incomplete_selection_evidence"
        )

    return {
        "players": players, "teams": teams, "entered": entered,
        "selected": selected, "leads": leads, "winner": winner,
        "turns_seen": active_turn, "confidence": confidence,
    }


def get_replay_id(item: dict) -> str | None:
    for key in ("id", "log", "url"):
        value = item.get(key)
        if isinstance(value, str) and value:
            if key == "id":
                return value
            match = re.search(r"(?:replay\.pokemonshowdown\.com/)?([a-z0-9-]+)(?:\.json|\.log)?$", value)
            if match:
                return match.group(1)
    return None


def search_replays(username: str, format_id: str, max_pages: int = 2) -> list[dict]:
    """Search a username; the API exposes up to 51 entries per page."""
    found: dict[str, dict] = {}
    before = None
    for page_no in range(max_pages):
        params = {"user": username, "format": format_id}
        if before:
            params["before"] = str(before)
        url = f"{API_ROOT}/search.json"
        payload = fetch_json(url, params=params)
        if not isinstance(payload, list) or not payload:
            break
        for item in payload:
            if not isinstance(item, dict):
                continue
            rid = get_replay_id(item)
            if rid:
                found[rid] = item
        # Search returns up to 51 results; paginate using the last result's uploadtime.
        if len(payload) <= 50:
            break
        last = payload[-1]
        before = last.get("uploadtime")
        if not before:
            break
        time.sleep(0.35)
    return list(found.values())


def replay_detail(replay_id: str) -> dict:
    return fetch_json(f"{API_ROOT}/{replay_id}.json")


def team_key(species: list[str]) -> str:
    # Species-only key: replay team preview cannot distinguish move/item variants.
    return "|".join(sorted(normalize_user(s) for s in species if s))


def upsert_replay(item: dict, format_id: str, requested_bot: str) -> tuple[bool, str]:
    replay_id = get_replay_id(item)
    if not replay_id:
        return False, "IDを判定できません"

    client = get_supabase()
    try:
        existing = (
            client.table("replays")
            .select("replay_id")
            .eq("replay_id", replay_id)
            .limit(1)
            .execute()
        )
        if existing.data:
            return False, "既に保存済み"
    except Exception as exc:
        raise RuntimeError(f"Supabaseの既存データ確認に失敗: {exc}") from exc

    detail = replay_detail(replay_id)
    log_text = detail.get("log") or ""
    p1 = detail.get("p1") or item.get("p1") or ""
    p2 = detail.get("p2") or item.get("p2") or ""
    parsed = parse_log(log_text, p1, p2)

    p1 = parsed["players"].get("p1") or p1
    p2 = parsed["players"].get("p2") or p2
    actual_format = str(detail.get("formatid") or detail.get("format") or format_id).strip().lower()
    if actual_format != DEFAULT_FORMAT:
        return False, f"対象外フォーマットのためスキップ: {actual_format}"

    uploadtime = detail.get("uploadtime") or item.get("uploadtime")
    rating = detail.get("rating") or item.get("rating")
    record = {
        "replay_id": replay_id,
        "replay_url": f"{API_ROOT}/{replay_id}",
        "format_id": actual_format,
        "uploadtime": int(uploadtime) if uploadtime not in (None, "") else None,
        "rating": int(rating) if rating not in (None, "") else None,
        "p1": p1,
        "p2": p2,
        "winner": parsed["winner"],
        "p1_team": json.dumps(parsed["teams"]["p1"], ensure_ascii=False),
        "p2_team": json.dumps(parsed["teams"]["p2"], ensure_ascii=False),
        "p1_selected": json.dumps(parsed["selected"]["p1"], ensure_ascii=False),
        "p2_selected": json.dumps(parsed["selected"]["p2"], ensure_ascii=False),
        "p1_leads": json.dumps(parsed["leads"]["p1"], ensure_ascii=False),
        "p2_leads": json.dumps(parsed["leads"]["p2"], ensure_ascii=False),
        "selection_confidence": json.dumps(parsed["confidence"], ensure_ascii=False),
        "log_text": log_text,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        client.table("replays").upsert(record, on_conflict="replay_id").execute()
    except Exception as exc:
        raise RuntimeError(f"Supabaseへの保存に失敗: {exc}") from exc
    return True, "Supabaseに保存しました"


def load_replays() -> pd.DataFrame:
    """Read all rows in pages to avoid Supabase's default row limit."""
    client = get_supabase()
    records: list[dict] = []
    page_size = 1000
    offset = 0
    while True:
        response = (
            client.table("replays")
            .select("*")
            .order("uploadtime", desc=True)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = response.data or []
        records.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return pd.DataFrame(records)


def reprocess_saved_selection_data() -> tuple[int, int, int, int]:
    """Re-parse stored logs; fetch the public replay again when log_text is missing."""
    client = get_supabase()
    response = client.table("replays").select(
        "replay_id,p1,p2,log_text,replay_url,format_id"
    ).eq("format_id", DEFAULT_FORMAT).execute()
    rows = response.data or []
    updated = 0
    fetched_logs = 0
    empty_logs = 0
    observed_sides = 0
    for row in rows:
        replay_id = row.get("replay_id")
        log_text = row.get("log_text") or ""
        # Some older rows were saved without the full log. Re-fetch those from Showdown.
        if not log_text.strip() and replay_id:
            try:
                detail = replay_detail(str(replay_id))
                log_text = detail.get("log") or ""
                if log_text.strip():
                    fetched_logs += 1
            except Exception:
                log_text = ""
        if not log_text.strip():
            empty_logs += 1
            continue
        parsed = parse_log(log_text, row.get("p1") or "", row.get("p2") or "")
        if parsed["entered"]["p1"] or parsed["entered"]["p2"]:
            observed_sides += 1
        update_record = {
            "p1": parsed["players"].get("p1") or row.get("p1") or "",
            "p2": parsed["players"].get("p2") or row.get("p2") or "",
            "winner": parsed["winner"],
            "p1_team": json.dumps(parsed["teams"]["p1"], ensure_ascii=False),
            "p2_team": json.dumps(parsed["teams"]["p2"], ensure_ascii=False),
            "p1_selected": json.dumps(parsed["selected"]["p1"], ensure_ascii=False),
            "p2_selected": json.dumps(parsed["selected"]["p2"], ensure_ascii=False),
            "p1_leads": json.dumps(parsed["leads"]["p1"], ensure_ascii=False),
            "p2_leads": json.dumps(parsed["leads"]["p2"], ensure_ascii=False),
            "selection_confidence": json.dumps(parsed["confidence"], ensure_ascii=False),
            "log_text": log_text,
        }
        client.table("replays").update(update_record).eq("replay_id", replay_id).execute()
        updated += 1
    return updated, fetched_logs, empty_logs, observed_sides


def as_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def winner_for_player(row: pd.Series, player: str) -> bool | None:
    if not row.get("winner"):
        return None
    return normalize_user(row["winner"]) == normalize_user(player)


# ----------------------------- Streamlit UI --------------------------------
st.set_page_config(page_title="Mikumiku Matchup Lab", page_icon="🎮", layout="wide")

# Streamlit's default metric values are oversized on narrow mobile screens.
# Reduce them only on phones so opponent-card stats remain compact and readable.
st.markdown(
    """
    <style>
    @media (max-width: 640px) {
        /* Only compact rows that actually contain metrics; leave other layouts alone. */
        [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) {
            flex-wrap: nowrap !important;
            gap: 0.25rem !important;
            width: 100% !important;
        }
        [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="column"] {
            min-width: 0 !important;
            width: 33.333% !important;
            max-width: 33.333% !important;
            flex: 1 1 33.333% !important;
            padding-left: 0.1rem !important;
            padding-right: 0.1rem !important;
        }
        [data-testid="stMetric"] {
            min-width: 0 !important;
            padding: 0.2rem 0 !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 0.95rem !important;
            line-height: 1.2 !important;
            overflow-wrap: anywhere !important;
            word-break: break-word !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.72rem !important;
            line-height: 1.15 !important;
            overflow-wrap: anywhere !important;
        }
        [data-testid="stMetricDelta"] {
            font-size: 0.68rem !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)
init_db()

st.title("🎮 Mikumiku Matchup Lab")
st.caption("Pokémon Showdown 公開リプレイ収集・構築別選出研究ツール")

with st.sidebar:
    st.header("収集設定")
    bots_text = st.text_area("対象ユーザー（1行に1人）", value="\n".join(DEFAULT_BOTS), height=90)
    bots = [line.strip() for line in bots_text.splitlines() if line.strip()]
    format_id = st.text_input("フォーマットID", value=DEFAULT_FORMAT)
    if format_id.strip().lower() != DEFAULT_FORMAT:
        st.warning("このツールはRegulation M-C専用です。フォーマットIDを gen9championsvgc2026regmc に戻してください。")
    max_pages = st.slider("ユーザーごとの検索ページ数", 1, 100, 20,
                          help="APIは検索1ページあたり最大51件。20ページなら最大約1,020件／ユーザー、100ページなら最大約5,100件／ユーザーです。ページ数を増やすと収集に時間がかかります。まずは20〜50ページがおすすめです。")
    st.caption("Reg M-C専用の形式ID: gen9championsvgc2026regmc")
    collect = st.button("🔄 公開リプレイを収集", type="primary", use_container_width=True)
    st.divider()
    st.header("分析条件")
    st.caption("分析対象：mikumiku37 と mikumiku38 を統合して集計")
    sheet_mode = st.radio("情報条件", ["クローズド", "OTS"], horizontal=True,
                          help="これは分析時の情報フィルターです。公開リプレイの内容自体が当時の情報開示を完全に示すとは限りません。")
    st.caption("注意：Closed / OTSは現在、表示上の分析条件です。公開リプレイだけでは対戦前の情報開示状態を完全復元できません。")

with st.sidebar:
    st.divider()
    repair_selection = st.button(
        "🛠️ 保存済みリプレイの選出情報を再解析",
        use_container_width=True,
        help="保存済みのログを修正版パーサーで読み直します。ログ本文が保存されているリプレイが対象です。",
    )

if repair_selection:
    try:
        with st.spinner("保存済みログから選出情報を再解析しています…"):
            updated_count, fetched_log_count, empty_log_count, observed_side_count = reprocess_saved_selection_data()
        st.success(f"再解析完了：{updated_count} 件を更新しました。場に出たポケモンを1体以上検出：{observed_side_count} 試合。")
        if fetched_log_count:
            st.info(f"ログをShowdownから再取得：{fetched_log_count} 件")
        if empty_log_count:
            st.warning(f"Showdownからもログ本文を取得できなかったため、{empty_log_count} 件は再解析できません。")
        st.rerun()
    except Exception as exc:
        st.error(f"再解析に失敗しました: {exc}")

if collect:
    if not bots:
        st.error("ユーザー名を1つ以上入力してください。")
    elif format_id.strip().lower() != DEFAULT_FORMAT:
        st.error("Regulation M-C専用です。フォーマットIDは gen9championsvgc2026regmc を使用してください。")
    else:
        progress = st.progress(0)
        status = st.empty()
        log_rows = []
        total = len(bots)
        count_saved = 0
        for i, bot_name in enumerate(bots):
            try:
                status.info(f"{bot_name} のリプレイを検索中…")
                results = search_replays(bot_name, format_id.strip(), max_pages)
                for j, item in enumerate(results):
                    try:
                        saved, message = upsert_replay(item, format_id.strip(), bot_name)
                        if saved:
                            count_saved += 1
                        log_rows.append({"ユーザー": bot_name, "リプレイ": get_replay_id(item), "結果": message})
                    except Exception as exc:
                        log_rows.append({"ユーザー": bot_name, "リプレイ": get_replay_id(item), "結果": f"取得失敗: {exc}"})
                    progress.progress(min(0.98, (i + (j + 1) / max(1, len(results))) / total))
            except Exception as exc:
                log_rows.append({"ユーザー": bot_name, "リプレイ": "", "結果": f"検索失敗: {exc}"})
            progress.progress((i + 1) / total)
        status.success(f"収集完了：新規 {count_saved} 件を保存")
        if log_rows:
            st.dataframe(pd.DataFrame(log_rows), use_container_width=True, hide_index=True)



# --------------------------- Page navigation -------------------------------
page = st.sidebar.radio(
    "ページ",
    ["分析ダッシュボード", "対策ノート"],
    index=0,
    key="main_page",
)

if page == "対策ノート":
    st.title("📝 対策ノート")
    st.caption("自分の構築ごとに、対戦前の作戦・初手の方針・対戦後の反省を保存します。")

    def note_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(x) for x in value if str(x).strip()]
        if not value:
            return []
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
            if isinstance(parsed, list):
                return [str(x) for x in parsed if str(x).strip()]
        except (ValueError, TypeError):
            pass
        return [x.strip() for x in str(value).replace(",", "\n").splitlines() if x.strip()]

    def get_notes():
        return get_supabase().table("strategy_notes").select("*").order(
            "updated_at", desc=True
        ).limit(1000).execute().data or []

    def parse_species_input(value: str) -> list[str]:
        # Accept one-per-line, comma-separated, or slash-separated species.
        raw = re.split(r"[\n,/、／]+", value or "")
        result = []
        for item in raw:
            species = item.strip()
            if species and species not in result:
                result.append(species)
        return result[:6]

    # Build known team choices from the replay table, retaining exact species names.
    try:
        replay_df_for_notes = load_replays()
        if not replay_df_for_notes.empty:
            replay_df_for_notes = replay_df_for_notes[
                replay_df_for_notes["format_id"].fillna("").str.lower() == DEFAULT_FORMAT
            ].copy()
    except Exception:
        replay_df_for_notes = pd.DataFrame()

    team_choices: dict[str, list[str]] = {}
    if not replay_df_for_notes.empty:
        for _, rr in replay_df_for_notes.iterrows():
            for side in ("p1", "p2"):
                player_name = str(rr.get(side) or "")
                if normalize_user(player_name) not in {normalize_user(x) for x in DEFAULT_BOTS}:
                    continue
                species = as_list(rr.get(f"{side}_team"))
                key = team_key(species)
                if key and species:
                    team_choices[key] = species

    team_keys = sorted(team_choices.keys(), key=lambda k: (-sum(1 for v in team_choices.values() if team_key(v) == k), k))
    team_labels = {k: " / ".join(team_choices[k]) for k in team_keys}
    team_options = ["手入力・未登録の構築"] + team_keys

    try:
        notes = get_notes()
        notes_error = None
    except Exception as exc:
        notes = []
        notes_error = str(exc)

    if notes_error:
        st.error(
            "対策ノート用の Supabase テーブルに接続できません。"
            "同梱の supabase_strategy_notes.sql を Supabase SQL Editor で実行してください。"
            f"\n\n詳細: {notes_error}"
        )
        st.stop()

    tab_quick, tab_new, tab_search, tab_edit = st.tabs(["⚡ 並びクイック検索", "➕ 新規ノート", "🔎 検索・一覧", "✏️ 編集・削除"])

    with tab_quick:
        st.subheader("⚡ 相手の並びをすばやく検索")
        st.caption("分かるポケモンだけ選べばOK。6匹すべて入力しなくても検索できます。")

        # Build a mobile-friendly species picker from saved notes and collected replays.
        species_pool = set()
        for note in notes:
            species_pool.update(note_list(note.get("opponent_team")))
        quick_replays = replay_df_for_notes.copy() if not replay_df_for_notes.empty else pd.DataFrame()
        if not quick_replays.empty:
            for _, replay_row in quick_replays.iterrows():
                p1_name = normalize_user(str(replay_row.get("p1") or ""))
                p2_name = normalize_user(str(replay_row.get("p2") or ""))
                if p1_name in {normalize_user(x) for x in DEFAULT_BOTS}:
                    species_pool.update(as_list(replay_row.get("p2_team")))
                elif p2_name in {normalize_user(x) for x in DEFAULT_BOTS}:
                    species_pool.update(as_list(replay_row.get("p1_team")))
        species_options = sorted((x for x in species_pool if x), key=str.casefold)

        # Recent / saved opponent lineups become one-tap presets on mobile.
        recent_lineups: list[tuple[str, list[str]]] = []
        seen_lineups: set[tuple[str, ...]] = set()
        for note in notes:
            lineup = note_list(note.get("opponent_team"))[:6]
            signature = tuple(sorted(normalize_user(x) for x in lineup if x))
            if lineup and signature not in seen_lineups:
                seen_lineups.add(signature)
                recent_lineups.append((str(note.get("title") or "保存済み対策ノート"), lineup))
        if not quick_replays.empty:
            bot_norms_for_presets = {normalize_user(x) for x in DEFAULT_BOTS}
            for _, replay_row in quick_replays.iterrows():
                p1_name = normalize_user(str(replay_row.get("p1") or ""))
                p2_name = normalize_user(str(replay_row.get("p2") or ""))
                if p1_name in bot_norms_for_presets:
                    lineup = as_list(replay_row.get("p2_team"))[:6]
                elif p2_name in bot_norms_for_presets:
                    lineup = as_list(replay_row.get("p1_team"))[:6]
                else:
                    continue
                signature = tuple(sorted(normalize_user(x) for x in lineup if x))
                if lineup and signature not in seen_lineups:
                    seen_lineups.add(signature)
                    recent_lineups.append(("過去リプレイ", lineup))
                if len(recent_lineups) >= 8:
                    break
        if recent_lineups:
            with st.expander("🕘 最近・保存済みの並びをワンタップ", expanded=True):
                st.caption("以前に記録した相手なら、ボタンを押すだけで検索欄にセットできます。")
                for preset_idx, (preset_title, preset_lineup) in enumerate(recent_lineups[:8]):
                    label = f"{preset_title[:18]}：{' / '.join(preset_lineup[:6])}"
                    if st.button(label, key=f"quick_lineup_preset_{preset_idx}", use_container_width=True):
                        st.session_state["quick_species_picker"] = preset_lineup[:6]
                        st.session_state["quick_min_matches"] = min(2, max(1, len(preset_lineup)))
                        st.rerun()

        quick_team_filter = st.selectbox(
            "自分の構築（任意）", ["すべての構築"] + team_keys,
            format_func=lambda k: "すべての構築" if k == "すべての構築" else team_labels.get(k, k),
            key="quick_team_filter",
        )
        picked_species = st.multiselect(
            "相手のポケモンを検索して追加（最大6匹）",
            options=species_options, max_selections=6,
            placeholder="タップして名前を入力・検索…", key="quick_species_picker",
            help="候補欄に英語名の一部を入力すると絞り込めます。分かるポケモンだけ選択してください。",
        )
        controls = st.columns([3, 2])
        with controls[0]:
            quick_min = st.select_slider(
                "最低一致数", options=[1, 2, 3, 4, 5, 6],
                value=min(2, max(1, len(picked_species))),
                format_func=lambda x: f"{x}匹以上", key="quick_min_matches",
            )
        with controls[1]:
            st.write("")
            st.write("")
            if st.button("選択をクリア", use_container_width=True, key="clear_quick_species"):
                st.session_state["quick_species_picker"] = []
                st.rerun()
        if not picked_species:
            st.info("上の欄をタップして、相手のポケモンを1匹以上選んでください。名前を全部入力する必要はありません。")
        else:
            picked_norm = {normalize_user(x) for x in picked_species}
            quick_results = []
            for note in notes:
                if quick_team_filter != "すべての構築" and note.get("our_team_key") != quick_team_filter:
                    continue
                opponent = note_list(note.get("opponent_team"))
                overlap = [x for x in opponent if normalize_user(x) in picked_norm]
                if len(overlap) >= quick_min:
                    quick_results.append({"kind": "note", "score": len(overlap), "overlap": overlap, "data": note})
            if not quick_replays.empty:
                bot_norms = {normalize_user(x) for x in DEFAULT_BOTS}
                for _, replay_row in quick_replays.iterrows():
                    p1_name = normalize_user(str(replay_row.get("p1") or ""))
                    p2_name = normalize_user(str(replay_row.get("p2") or ""))
                    if p1_name in bot_norms:
                        opponent = as_list(replay_row.get("p2_team")); own_species = as_list(replay_row.get("p1_team"))
                    elif p2_name in bot_norms:
                        opponent = as_list(replay_row.get("p1_team")); own_species = as_list(replay_row.get("p2_team"))
                    else:
                        continue
                    if quick_team_filter != "すべての構築" and team_key(own_species) != quick_team_filter:
                        continue
                    overlap = [x for x in opponent if normalize_user(x) in picked_norm]
                    if len(overlap) >= quick_min:
                        quick_results.append({"kind": "replay", "score": len(overlap), "overlap": overlap, "data": replay_row.to_dict(), "opponent": opponent})
            quick_results.sort(key=lambda r: (-r["score"], 0 if r["kind"] == "note" else 1))
            st.markdown(f"**{len(quick_results)} 件ヒット**　・一致数が多い順")
            if not quick_results:
                st.warning("一致する記録がありません。一致条件を1匹に下げるか、別のポケモンを選んでください。")
            for idx, item in enumerate(quick_results[:40], start=1):
                if item["kind"] == "note":
                    n = item["data"]
                    with st.container(border=True):
                        st.markdown(f"**📝 対策ノート：{n.get('title') or '名称未設定'}**")
                        st.caption(f"一致 {item['score']}匹：{' / '.join(item['overlap'])}　｜　結果：{n.get('result') or '未対戦'}")
                        st.markdown("**相手の並び**：" + (" / ".join(note_list(n.get("opponent_team"))) or "未登録"))
                        st.markdown("**先発候補**：" + (n.get("lead_plan") or "未登録"))
                        if n.get("opening_plan"):
                            st.info("🎯 初手プラン\n\n" + str(n.get("opening_plan")))
                        else:
                            st.caption("初手プラン：未登録")
                        if n.get("threats"):
                            st.warning("⚠️ 警戒ポイント\n\n" + str(n.get("threats")))
                        if n.get("next_action"):
                            st.markdown("**次回やること**：" + str(n.get("next_action")))
                else:
                    r = item["data"]
                    with st.container(border=True):
                        st.markdown(f"**🎮 過去リプレイ：一致 {item['score']}匹**")
                        st.caption("一致：" + " / ".join(item["overlap"]))
                        st.markdown("**相手の並び**：" + (" / ".join(item.get("opponent", [])) or "不明"))
                        bot_names = [str(r.get(k) or "") for k in ("p1", "p2")]
                        st.caption(f"対戦者：{' vs '.join(x for x in bot_names if x)}　｜　ターン数：{r.get('turns_seen') or '不明'}")
                        replay_url = r.get("replay_url") or f"{API_ROOT}/{r.get('replay_id')}"
                        if replay_url:
                            st.link_button("リプレイを開く", replay_url, use_container_width=True, key=f"quick_replay_{idx}")
            if len(quick_results) > 40:
                st.caption("表示は上位40件までです。ポケモンを追加すると絞り込めます。")

    with tab_new:
        st.subheader("対戦前の作戦を登録")
        st.caption("構築を選んでから、相手の6匹と初手プランを記録します。入力内容はSupabaseに保存されます。")
        with st.form("strategy_note_create", clear_on_submit=True):
            title = st.text_input("ノート名 *", placeholder="例：追い風＋高火力構築への対策")
            chosen_team = st.selectbox(
                "自分の構築 *",
                team_options,
                format_func=lambda k: "手入力・未登録の構築" if k == "手入力・未登録の構築" else team_labels.get(k, k),
            )
            if chosen_team == "手入力・未登録の構築":
                own_team_text = st.text_area("自分の構築（最大6匹・改行または / 区切り）", height=90)
            else:
                own_team_text = ""
                st.caption("選択中の自分の構築：" + team_labels.get(chosen_team, ""))
            opponent_text = st.text_area(
                "相手の構築（最大6匹・改行、カンマ、/ 区切り）",
                height=110,
                placeholder="Whimsicott\nCharizard\nBasculegion\nKingambit\nFloette-Eternal\nGarchomp",
            )
            col1, col2 = st.columns(2)
            with col1:
                lead_plan = st.text_input("自分の先発候補", placeholder="例：Rillaboom＋Incineroar")
                opening_plan = st.text_area("初手の行動方針", height=120, placeholder="初手に何をするか、技・交代・守るの候補など")
                conditions = st.text_area("対策を使う条件・分岐", height=90, placeholder="例：相手が追い風を選びそうなら…")
            with col2:
                threats = st.text_area("警戒する要素", height=120, placeholder="例：追い風、ねこだまし、トリックルーム")
                next_action = st.text_area("次回に確認すること", height=90, placeholder="例：別の先発候補も試す")
                replay_id = st.text_input("関連リプレイID（任意）", placeholder="例：gen9championsvgc2026regmc-2692405047")
            submitted = st.form_submit_button("💾 対策ノートを保存", type="primary", use_container_width=True)

        if submitted:
            own_species = team_choices.get(chosen_team, []) if chosen_team != "手入力・未登録の構築" else parse_species_input(own_team_text)
            opponent_species = parse_species_input(opponent_text)
            if not title.strip():
                st.error("ノート名を入力してください。")
            elif not own_species:
                st.error("自分の構築を選ぶか、少なくとも1匹を入力してください。")
            elif len(own_species) > 6 or len(opponent_species) > 6:
                st.error("構築は最大6匹まで登録できます。")
            else:
                record = {
                    "title": title.strip(),
                    "our_team_key": team_key(own_species),
                    "our_team_species": own_species,
                    "opponent_team": opponent_species,
                    "lead_plan": lead_plan.strip(),
                    "opening_plan": opening_plan.strip(),
                    "threats": threats.strip(),
                    "conditions": conditions.strip(),
                    "result": "未対戦",
                    "actual_leads": [],
                    "review": "",
                    "next_action": next_action.strip(),
                    "replay_id": replay_id.strip() or None,
                }
                try:
                    get_supabase().table("strategy_notes").insert(record).execute()
                    st.success("対策ノートをSupabaseに保存しました。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"保存に失敗しました: {exc}")

    with tab_search:
        st.subheader("保存済みノートを検索")
        search_col1, search_col2 = st.columns([2, 1])
        with search_col1:
            query = st.text_input("キーワード", placeholder="ノート名・ポケモン・初手・反省メモ")
        with search_col2:
            result_filter = st.selectbox("結果", ["すべて", "未対戦", "勝ち", "負け", "引き分け"])
        team_filter_options = ["すべての構築"] + team_keys
        team_filter = st.selectbox(
            "自分の構築で絞り込み",
            team_filter_options,
            format_func=lambda k: "すべての構築" if k == "すべての構築" else team_labels.get(k, k),
        )
        filtered_notes = []
        q = query.strip().casefold()
        for note in notes:
            if result_filter != "すべて" and (note.get("result") or "未対戦") != result_filter:
                continue
            if team_filter != "すべての構築" and note.get("our_team_key") != team_filter:
                continue
            haystack = " ".join([
                str(note.get("title") or ""),
                " ".join(note_list(note.get("our_team_species"))),
                " ".join(note_list(note.get("opponent_team"))),
                str(note.get("lead_plan") or ""),
                str(note.get("opening_plan") or ""),
                str(note.get("threats") or ""),
                str(note.get("conditions") or ""),
                str(note.get("review") or ""),
                str(note.get("next_action") or ""),
            ]).casefold()
            if q and q not in haystack:
                continue
            filtered_notes.append(note)
        st.caption(f"{len(filtered_notes)} 件")
        if filtered_notes:
            rows = []
            for n in filtered_notes:
                rows.append({
                    "ID": n.get("id"),
                    "ノート名": n.get("title", ""),
                    "自分の構築": " / ".join(note_list(n.get("our_team_species"))),
                    "相手の構築": " / ".join(note_list(n.get("opponent_team"))),
                    "先発候補": n.get("lead_plan", ""),
                    "結果": n.get("result") or "未対戦",
                    "更新日時": str(n.get("updated_at") or n.get("created_at") or ""),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            for n in filtered_notes:
                with st.expander(f"📌 {n.get('title') or '名称未設定'} — {n.get('result') or '未対戦'}"):
                    st.markdown("**自分の構築**：" + (" / ".join(note_list(n.get("our_team_species"))) or "未登録"))
                    st.markdown("**相手の構築**：" + (" / ".join(note_list(n.get("opponent_team"))) or "未登録"))
                    st.markdown("**先発候補**：" + (n.get("lead_plan") or "未登録"))
                    st.markdown("**初手の行動方針**")
                    st.write(n.get("opening_plan") or "未登録")
                    st.markdown("**警戒する要素**")
                    st.write(n.get("threats") or "未登録")
                    st.markdown("**対策を使う条件**")
                    st.write(n.get("conditions") or "未登録")
                    st.markdown("**対戦後の振り返り**")
                    st.write(n.get("review") or "まだ記録されていません")
                    if n.get("replay_id"):
                        st.link_button("関連リプレイを開く", f"{API_ROOT}/{n['replay_id']}")
        else:
            st.info("条件に一致する対策ノートはありません。")

    with tab_edit:
        st.subheader("ノートの編集・削除")
        if not notes:
            st.info("編集できるノートがありません。まず新規ノートを保存してください。")
        else:
            note_map = {
                str(n.get("id")): f"{n.get('title') or '名称未設定'}｜{' / '.join(note_list(n.get('our_team_species'))[:3])}｜{n.get('result') or '未対戦'}"
                for n in notes
            }
            chosen_id = st.selectbox("編集するノート", list(note_map.keys()), format_func=lambda k: note_map[k])
            current = next(n for n in notes if str(n.get("id")) == chosen_id)
            with st.form("strategy_note_edit"):
                edit_title = st.text_input("ノート名 *", value=current.get("title") or "")
                edit_own_team = st.text_area(
                    "自分の構築（最大6匹）",
                    value="\n".join(note_list(current.get("our_team_species"))),
                    height=100,
                )
                edit_opponent = st.text_area(
                    "相手の構築（最大6匹）",
                    value="\n".join(note_list(current.get("opponent_team"))),
                    height=100,
                )
                edit_lead = st.text_input("自分の先発候補", value=current.get("lead_plan") or "")
                edit_opening = st.text_area("初手の行動方針", value=current.get("opening_plan") or "", height=120)
                edit_threats = st.text_area("警戒する要素", value=current.get("threats") or "", height=90)
                edit_conditions = st.text_area("対策を使う条件・分岐", value=current.get("conditions") or "", height=90)
                edit_result = st.selectbox(
                    "対戦結果",
                    ["未対戦", "勝ち", "負け", "引き分け"],
                    index=["未対戦", "勝ち", "負け", "引き分け"].index(current.get("result") or "未対戦")
                    if (current.get("result") or "未対戦") in ["未対戦", "勝ち", "負け", "引き分け"] else 0,
                )
                edit_actual_leads = st.text_input(
                    "実際の先発（任意）",
                    value=" / ".join(note_list(current.get("actual_leads"))),
                )
                edit_review = st.text_area("対戦後の振り返り", value=current.get("review") or "", height=120)
                edit_next = st.text_area("次回に確認すること", value=current.get("next_action") or "", height=90)
                edit_replay = st.text_input("関連リプレイID（任意）", value=current.get("replay_id") or "")
                save_edit = st.form_submit_button("変更を保存", type="primary", use_container_width=True)
            if save_edit:
                own_species = parse_species_input(edit_own_team)
                opponent_species = parse_species_input(edit_opponent)
                if not edit_title.strip():
                    st.error("ノート名を入力してください。")
                elif not own_species:
                    st.error("自分の構築を1匹以上入力してください。")
                else:
                    update_record = {
                        "title": edit_title.strip(),
                        "our_team_key": team_key(own_species),
                        "our_team_species": own_species,
                        "opponent_team": opponent_species,
                        "lead_plan": edit_lead.strip(),
                        "opening_plan": edit_opening.strip(),
                        "threats": edit_threats.strip(),
                        "conditions": edit_conditions.strip(),
                        "result": edit_result,
                        "actual_leads": parse_species_input(edit_actual_leads),
                        "review": edit_review.strip(),
                        "next_action": edit_next.strip(),
                        "replay_id": edit_replay.strip() or None,
                    }
                    try:
                        get_supabase().table("strategy_notes").update(update_record).eq("id", chosen_id).execute()
                        st.success("ノートを更新しました。")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"更新に失敗しました: {exc}")

            st.divider()
            st.warning("削除したノートは復元できません。")
            confirm_delete = st.checkbox("このノートを削除することを確認しました", key=f"delete_confirm_{chosen_id}")
            if st.button("🗑️ このノートを削除", disabled=not confirm_delete, key=f"delete_note_{chosen_id}"):
                try:
                    get_supabase().table("strategy_notes").delete().eq("id", chosen_id).execute()
                    st.success("ノートを削除しました。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"削除に失敗しました: {exc}")

    st.stop()

df = load_replays()
if not df.empty:
    df = df[df["format_id"].fillna("").str.lower() == DEFAULT_FORMAT].copy()

if df.empty:
    st.info("まだデータがありません。左側の「公開リプレイを収集」を押して収集を開始してください。")
    st.markdown("""
    **最初に確認すること**
    1. フォーマットIDが現在のルールに一致しているか確認する
    2. 対象ユーザーが公開リプレイを保存しているか確認する
    3. 検索結果が0件なら、Showdownのリプレイ検索ページでユーザー名と形式を直接確認する
    """)
    st.link_button("Showdown リプレイ検索", "https://replay.pokemonshowdown.com/")
    st.stop()

# Decode fields into convenient columns.
for col in ["p1_team", "p2_team", "p1_selected", "p2_selected", "p1_leads", "p2_leads"]:
    df[col + "_list"] = df[col].apply(as_list)

def bot_side(row: pd.Series, names: list[str]) -> str | None:
    normalized = {normalize_user(n) for n in names}
    if normalize_user(row.get("p1", "")) in normalized:
        return "p1"
    if normalize_user(row.get("p2", "")) in normalized:
        return "p2"
    return None

# 2アカウントを「自分側」として統合。1試合につき1行（replay_id）だけを集計する。
target_names = DEFAULT_BOTS
df["bot_side"] = df.apply(lambda row: bot_side(row, target_names), axis=1)
bot_df = df[df["bot_side"].notna()].copy()
df["bot_side_all"] = df.apply(lambda row: bot_side(row, DEFAULT_BOTS), axis=1)
all_bot_df = df[df["bot_side_all"].notna()].copy()

# Main metrics
c1, c2, c3, c4 = st.columns(4)
c1.metric("保存済みリプレイ", len(df))
c2.metric("対象BOTの対戦", len(bot_df))
c3.metric("構築候補（6体一致）", len({team_key(as_list(r["p1_team"]) if r["bot_side"] == "p1" else as_list(r["p2_team"])) for _, r in bot_df.iterrows()} - {""}))
wins = sum(1 for _, row in bot_df.iterrows() if winner_for_player(row, row["p1"] if row["bot_side"] == "p1" else row["p2"]) is True)
decided = sum(1 for _, row in bot_df.iterrows() if row.get("winner"))
c4.metric("対象BOTの勝率", f"{wins / decided:.1%}" if decided else "—")

st.subheader("構築別の対戦データ")
st.caption("構築の識別はチームプレビューの種族6体に基づきます。技・持ち物・特性・テラスタイプ違いは、リプレイ情報だけでは別構築と断定できません。")

team_rows = []
for _, row in bot_df.iterrows():
    side = row["bot_side"]
    team = as_list(row[f"{side}_team"])
    opp_side = "p2" if side == "p1" else "p1"
    opp_team = as_list(row[f"{opp_side}_team"])
    bot_name = row[side]
    won = winner_for_player(row, bot_name)
    key = team_key(team)
    team_rows.append({
        "構築キー": key,
        "構築（確認できた6体）": " / ".join(team),
        "相手の6体": " / ".join(opp_team),
        "勝敗": "勝ち" if won is True else ("負け" if won is False else "不明"),
        "レート": row["rating"],
        "日時": datetime.fromtimestamp(row["uploadtime"]).strftime("%Y-%m-%d %H:%M") if row["uploadtime"] else "",
        "リプレイ": row["replay_url"],
        "選出判定": json.loads(row["selection_confidence"] or "{}").get(side, "不明"),
        "先発候補（ログ上の初登場2体）": " / ".join(as_list(row[f"{side}_leads"])),
        "選出候補（ログ上で場に出た最大4体）": " / ".join(as_list(row[f"{side}_selected"])),
    })
team_df = pd.DataFrame(team_rows)

if team_df.empty:
    st.warning("保存済みデータに対象BOTの対戦が見つかりません。ユーザー名・フォーマットID・公開リプレイの有無を確認してください。")
else:
    # 対戦数が多い構築を先頭に表示（同数の場合は構築キー順）。
    team_match_counts = team_df["構築キー"].value_counts()
    unique_teams = sorted(
        team_match_counts.index.tolist(),
        key=lambda key: (-int(team_match_counts[key]), str(key)),
    )
    labels = {}
    for i, key in enumerate(unique_teams, 1):
        sample = team_df[team_df["構築キー"] == key].iloc[0]
        species = sample["構築（確認できた6体）"]
        matches = int(team_match_counts[key])
        labels[key] = f"{i}位｜{matches}試合 — {species[:75]}"
    selected_key = st.selectbox("分析する構築（試合数が多い順）", unique_teams, format_func=lambda x: labels.get(x, x))
    selected_team_df = team_df[team_df["構築キー"] == selected_key].copy()

    a, b, c = st.columns(3)
    a.metric("この構築の対戦数", len(selected_team_df))
    known = selected_team_df[selected_team_df["勝敗"].isin(["勝ち", "負け"])]
    b.metric("勝率", f"{(known['勝敗'] == '勝ち').mean():.1%}" if len(known) else "—")
    c.metric("相手の並びの種類", selected_team_df["相手の6体"].nunique())

    # Group matches by opponent lineup so repeated teams appear as one compact mobile card.
    st.caption("相手の並びが同じ対戦は1つにまとめ、選出候補とリプレイは折りたたんで表示します。")
    selected_team_df["_相手キー"] = selected_team_df["相手の6体"].apply(
        lambda value: team_key([x.strip() for x in str(value or "").split("/") if x.strip()])
    )
    opponent_groups = []
    for opponent_key, group in selected_team_df.groupby("_相手キー", dropna=False, sort=False):
        group = group.copy()
        group = group.sort_values("日時", ascending=False)
        sample = group.iloc[0]
        wins_count = int((group["勝敗"] == "勝ち").sum())
        losses_count = int((group["勝敗"] == "負け").sum())
        unknown_count = int((~group["勝敗"].isin(["勝ち", "負け"])).sum())
        decided_count = wins_count + losses_count
        win_rate = f"{wins_count / decided_count:.1%}" if decided_count else "—"
        opponent_groups.append((group, sample, wins_count, losses_count, unknown_count, win_rate))
    opponent_groups.sort(key=lambda item: (-len(item[0]), str(item[1].get("相手の6体") or "")))

    for group_index, (group, match, wins_count, losses_count, unknown_count, win_rate) in enumerate(opponent_groups):
        outcome_summary = f"{wins_count}勝{losses_count}敗"
        if unknown_count:
            outcome_summary += f"・結果不明{unknown_count}"
        opponent_species = [x.strip() for x in str(match.get("相手の6体") or "").split("/") if x.strip()]
        with st.container(border=True):
            st.markdown(f"**相手の並び · {len(group)}試合**")
            render_species_icons(opponent_species, max_items=6, size=40)
            metric_left, metric_mid, metric_right = st.columns(3)
            metric_left.metric("対戦数", len(group))
            metric_mid.metric("勝敗", outcome_summary)
            metric_right.metric("勝率", win_rate)
            with st.expander(f"選出候補・リプレイを表示（{len(group)}試合）"):
                for replay_index, (_, replay_match) in enumerate(group.iterrows(), 1):
                    outcome = str(replay_match.get("勝敗") or "不明")
                    result_icon = "🟢" if outcome == "勝ち" else ("🔴" if outcome == "負け" else "⚪")
                    st.markdown(f"**{replay_index}. {result_icon} {outcome}**")
                    info_left, info_right = st.columns(2)
                    with info_left:
                        st.caption("選出判定")
                        confidence = str(replay_match.get("選出判定") or "不明")
                        st.write("4体観測" if confidence == "observed_entries_only" else
                                 ("観測不足" if confidence == "incomplete_selection_evidence" else confidence))
                    with info_right:
                        st.caption("日時・レート")
                        rating_value = replay_match.get("レート")
                        rating_text = f"R: {int(rating_value)}" if pd.notna(rating_value) else "R: —"
                        st.write(f"{replay_match.get('日時') or '日時不明'} · {rating_text}")
                    with st.expander("先発候補"):
                        lead_species = [x.strip() for x in str(replay_match.get("先発候補（ログ上の初登場2体）") or "").split("/") if x.strip()]
                        render_species_icons(lead_species, max_items=2, size=40)
                    st.markdown("**選出候補（ログ上で場に出た最大4体）**")
                    selected_species = [x.strip() for x in str(replay_match.get("選出候補（ログ上で場に出た最大4体）") or "").split("/") if x.strip()]
                    render_species_icons(selected_species, max_items=4, size=36)
                    replay_url = str(replay_match.get("リプレイ") or "")
                    if replay_url:
                        st.link_button("🔗 リプレイを開く", replay_url, use_container_width=True)
                    if replay_index < len(group):
                        st.divider()

    st.subheader("相手の構築に対する選出傾向")
    st.caption("ここに表示するのは、リプレイログで実際に場に出たことを確認できたポケモンです。未登場の選出ポケモンは公開ログだけでは確定できません。選出判定欄の incomplete_selection_evidence は「4体すべて確認できなかった」という意味で、観測済みのポケモンまで無効という意味ではありません。")
    lead_counts = Counter()
    bring_counts = Counter()
    for _, row in selected_team_df.iterrows():
        lead_counts.update(as_list(row["先発候補（ログ上の初登場2体）"]))
        bring_counts.update(as_list(row["選出候補（ログ上で場に出た最大4体）"]))
    if lead_counts:
        st.markdown("**先発として最初に観測されたポケモン**")
        lead_df = pd.DataFrame(lead_counts.most_common(), columns=["ポケモン", "観測回数"])
        st.bar_chart(lead_df.set_index("ポケモン"))
    if bring_counts:
        st.markdown("**場に出たポケモン（最大4体まで観測）**")
        bring_df = pd.DataFrame(bring_counts.most_common(), columns=["ポケモン", "観測回数"])
        st.bar_chart(bring_df.set_index("ポケモン"))

    st.subheader("相手の並び別の記録")
    by_opp = selected_team_df.groupby("相手の6体", dropna=False).agg(
        対戦数=("勝敗", "size"),
        勝ち=("勝敗", lambda s: int((s == "勝ち").sum())),
        負け=("勝敗", lambda s: int((s == "負け").sum())),
    ).reset_index().sort_values("対戦数", ascending=False)
    if not by_opp.empty:
        by_opp["勝率（判明分）"] = by_opp.apply(
            lambda r: f"{r['勝ち'] / (r['勝ち'] + r['負け']):.1%}" if r["勝ち"] + r["負け"] else "—", axis=1
        )
        # Compact cards are easier to read and tap on narrow mobile screens.
        for _, opp_row in by_opp.iterrows():
            with st.container(border=True):
                st.markdown(f"**相手の並び**")
                st.write(str(opp_row["相手の6体"] or "未取得"))
                metric_left, metric_mid, metric_right = st.columns(3)
                metric_left.metric("対戦数", int(opp_row["対戦数"]))
                metric_mid.metric("勝ち", int(opp_row["勝ち"]))
                metric_right.metric("負け", int(opp_row["負け"]))
                st.caption(f"勝率（判明分）：{opp_row['勝率（判明分）']}")

st.subheader("全リプレイ一覧")
show_cols = ["replay_id", "format_id", "p1", "p2", "winner", "rating", "uploadtime", "replay_url"]
view_df = df[show_cols].copy()
view_df["uploadtime"] = view_df["uploadtime"].apply(
    lambda x: datetime.fromtimestamp(x).strftime("%Y-%m-%d %H:%M") if pd.notna(x) and x else ""
)
# Keep the full replay history usable on phones; put details behind an expander.
for _, replay_row in view_df.head(100).iterrows():
    with st.container(border=True):
        st.markdown(f"**{replay_row.get('p1') or '?'} vs {replay_row.get('p2') or '?'}**")
        st.caption(f"{replay_row.get('uploadtime') or '日時不明'} · {replay_row.get('format_id') or ''}")
        result_text = "勝者：" + str(replay_row.get("winner") or "不明")
        st.write(result_text)
        with st.expander("リプレイ情報"):
            st.write(f"ID：{replay_row.get('replay_id') or '—'}")
            st.write(f"レート：{replay_row.get('rating') if pd.notna(replay_row.get('rating')) else '—'}")
            replay_url = str(replay_row.get("replay_url") or "")
            if replay_url:
                st.link_button("🔗 リプレイを開く", replay_url, use_container_width=True)
if len(view_df) > 100:
    st.caption(f"スマホ表示は先頭100件です（全{len(view_df)}件）。CSVから全件を保存できます。")

st.download_button(
    "⬇️ 収集データをCSVで保存",
    data=df.drop(columns=[c for c in df.columns if c.endswith("_list")], errors="ignore").to_csv(index=False).encode("utf-8-sig"),
    file_name="mikumiku_replays.csv",
    mime="text/csv",
)

with st.expander("クローズド／OTSの扱いとデータ品質について"):
    st.markdown("""
    - **クローズド**：相手の技・持ち物・特性などを事前情報として補完しません。ただし、この第1版ではセット情報を使った予測モデル自体はまだ実装していません。
    - **OTS**：公開されているリプレイログから相手セットを完全復元する機能は未実装です。OTSの切り替えは次段階で、対戦前に公開されていた情報だけを入力・利用する形に拡張します。
    - **選出の制約**：ログに出たポケモンから選出を推定しますが、場に出なかった選出ポケモンは特定できないことがあります。表示は「選出確定」ではなく「ログ上の観測」です。
    - **構築の制約**：6体の種族一致でまとめています。技・持ち物などを含む完全な構築の違いは、ユーザーが手動でラベル付けする機能を今後追加します。
    - 公開リプレイ検索に結果がない場合、非公開リプレイや保存されていない対戦は取得できません。
    """)

st.caption("Mikumiku Matchup Lab v0.3 · 選出ログ解析を修正。mikumiku37 / mikumiku38 は統合して分析します。")
