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
                if species and species not in entered[side]:
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


def reprocess_saved_selection_data() -> tuple[int, int]:
    """Re-parse stored public logs to repair selection data without refetching replays."""
    client = get_supabase()
    response = client.table("replays").select(
        "replay_id,p1,p2,log_text"
    ).eq("format_id", DEFAULT_FORMAT).execute()
    rows = response.data or []
    updated = 0
    empty_logs = 0
    for row in rows:
        log_text = row.get("log_text") or ""
        if not log_text.strip():
            empty_logs += 1
            continue
        parsed = parse_log(log_text, row.get("p1") or "", row.get("p2") or "")
        client.table("replays").update({
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
        }).eq("replay_id", row["replay_id"]).execute()
        updated += 1
    return updated, empty_logs


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
    max_pages = st.slider("ユーザーごとの検索ページ数", 1, 50, 10,
                          help="APIは検索1ページあたり最大51件。10ページなら最大約510件／ユーザー、50ページなら最大約2,550件／ユーザーです。過去のリプレイほど取得に時間がかかります。")
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
            updated_count, empty_log_count = reprocess_saved_selection_data()
        st.success(f"再解析完了：{updated_count} 件を更新しました。")
        if empty_log_count:
            st.warning(f"ログ本文が保存されていないため、{empty_log_count} 件は再解析できません。")
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

    st.dataframe(
        selected_team_df[["相手の6体", "勝敗", "レート", "日時", "選出判定",
                          "先発候補（ログ上の初登場2体）", "選出候補（ログ上で場に出た最大4体）", "リプレイ"]],
        use_container_width=True, hide_index=True,
        column_config={"リプレイ": st.column_config.LinkColumn("リプレイ", display_text="開く")}
    )

    st.subheader("相手の構築に対する選出傾向")
    st.caption("ここに表示するのは、リプレイで観測できた場への登場順です。未登場の選出ポケモンは復元できない場合があるため、選出率の確定値とは扱いません。")
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
        st.dataframe(by_opp, use_container_width=True, hide_index=True)

st.subheader("全リプレイ一覧")
show_cols = ["replay_id", "format_id", "p1", "p2", "winner", "rating", "uploadtime", "replay_url"]
view_df = df[show_cols].copy()
view_df["uploadtime"] = view_df["uploadtime"].apply(
    lambda x: datetime.fromtimestamp(x).strftime("%Y-%m-%d %H:%M") if pd.notna(x) and x else ""
)
st.dataframe(view_df, use_container_width=True, hide_index=True,
             column_config={"replay_url": st.column_config.LinkColumn("URL", display_text="開く")})

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
