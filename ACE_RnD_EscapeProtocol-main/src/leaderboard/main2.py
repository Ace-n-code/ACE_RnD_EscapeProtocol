import html
import time

import pandas as pd
import requests
import streamlit as st

# RUN: streamlit run src/leaderboard/main2.py

# =====================================================================
#  Configuration
# =====================================================================
st.set_page_config(layout="wide", page_title="Escape Protocol", page_icon="🐢")

DEFAULT_API_BASE = "https://ace-rnd-escapeprotocol.onrender.com"


def get_api_base():
    try:
        return st.secrets.get("API_BASE", DEFAULT_API_BASE).rstrip("/")
    except Exception:
        return DEFAULT_API_BASE


API_BASE = get_api_base()
REFRESH_SECONDS = 10

STATUS_LABELS = {
    "active": "🟢 Live",
    "completed": "🏁 Completed",
    "upcoming": "⏳ Upcoming",
}

# =====================================================================
#  Styling
# =====================================================================
st.markdown(
    """
    <style>
    .block-container { padding-top: 1.5rem; }
    .hero {
        padding: 1.4rem 1.8rem;
        border-radius: 16px;
        background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 55%, #0ea5e9 100%);
        color: #ffffff;
        margin-bottom: 1rem;
    }
    .hero h1 { margin: 0; font-size: 2.1rem; color: #ffffff; }
    .hero p  { margin: 0.2rem 0 0 0; opacity: 0.85; }
    .badge {
        display: inline-block; padding: 0.15rem 0.7rem; border-radius: 999px;
        font-size: 0.8rem; font-weight: 600; margin-left: 0.6rem;
        background: rgba(255,255,255,0.18); border: 1px solid rgba(255,255,255,0.35);
        vertical-align: middle;
    }
    .pod-medal { font-size: 2.4rem; text-align: center; line-height: 1.1; }
    .pod-name  { font-size: 1.25rem; font-weight: 700; text-align: center;
                 overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .pod-score { font-size: 1.6rem; font-weight: 800; text-align: center; }
    .pod-sub   { text-align: center; opacity: 0.7; font-size: 0.85rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# =====================================================================
#  Data fetching
# =====================================================================
EMPTY_COLUMNS = [
    "username", "Total Score", "Total Moves", "Total Distance (units)",
    "Total Time (s)", "Mazes Completed", "mazes",
]


@st.cache_data(ttl=60, show_spinner=False)
def fetch_seasons():
    """Returns ({'current': id, 'seasons': [...]}, error)."""
    try:
        r = requests.get(f"{API_BASE}/seasons", timeout=60)
        r.raise_for_status()
        return r.json(), None
    except requests.exceptions.RequestException as e:
        return None, f"❌ Could not reach the API: {e}"
    except Exception as e:
        return None, f"❌ Could not load seasons: {e}"


def build_df(data):
    """Turns the API response into a clean, ranked DataFrame."""
    if not data:
        return pd.DataFrame(columns=EMPTY_COLUMNS + ["Rank"])

    for entry in data:
        entry.setdefault("mazes", {})

    df = pd.DataFrame(data).rename(columns={
        "total": "Total Score",
        "total_moves": "Total Moves",
        "total_distance": "Total Distance (units)",
        "total_time": "Total Time (s)",
        "mazes_completed": "Mazes Completed",
    })

    # Highest score first; faster total time breaks ties
    df = df.sort_values(
        by=["Total Score", "Total Time (s)"], ascending=[False, True]
    ).reset_index(drop=True)

    df["_rank"] = df["Total Score"].rank(method="min", ascending=False).astype(int)
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    df["Rank"] = df["_rank"].map(lambda r: medals.get(r, str(r)))
    return df


@st.cache_data(ttl=5, show_spinner=False)
def fetch_leaderboard(season_id):
    try:
        r = requests.get(
            f"{API_BASE}/leaderboard", params={"season": season_id}, timeout=60
        )
        r.raise_for_status()
        return build_df(r.json()), None
    except requests.exceptions.RequestException as e:
        return pd.DataFrame(), f"❌ Error connecting to API: {e}"
    except Exception as e:
        return pd.DataFrame(), f"❌ Error processing data: {e}"


@st.cache_data(ttl=300, show_spinner=False)
def fetch_champion(season_id):
    """Top player + player count for a season (used on the Champions tab)."""
    try:
        r = requests.get(
            f"{API_BASE}/leaderboard", params={"season": season_id}, timeout=60
        )
        r.raise_for_status()
        df = build_df(r.json())
        if df.empty:
            return None
        top = df.iloc[0]
        return {
            "Champion": top["username"],
            "Score": float(top["Total Score"]),
            "Mazes": int(top["Mazes Completed"]),
            "Players": int(len(df)),
        }
    except Exception:
        return None


# =====================================================================
#  UI helpers
# =====================================================================
def show_df(df, **kwargs):
    """st.dataframe that works across Streamlit versions."""
    try:
        st.dataframe(df, width="stretch", hide_index=True, **kwargs)
    except TypeError:
        st.dataframe(df, use_container_width=True, hide_index=True, **kwargs)


def render_podium(df):
    top = df.head(3)
    medals = ["🥇", "🥈", "🥉"]
    cols = st.columns(3)
    for col, (_, row), medal in zip(cols, top.iterrows(), medals):
        with col.container(border=True):
            name = html.escape(str(row["username"]))
            st.markdown(
                f"<div class='pod-medal'>{medal}</div>"
                f"<div class='pod-name'>{name}</div>"
                f"<div class='pod-score'>{row['Total Score']:.2f}</div>"
                f"<div class='pod-sub'>{int(row['Mazes Completed'])} mazes · "
                f"{int(row['Total Moves']):,} moves</div>",
                unsafe_allow_html=True,
            )


def build_maze_records(df):
    records = []
    for _, user_row in df.iterrows():
        for maze_name, metrics in (user_row.get("mazes") or {}).items():
            # metrics = [score, move_count, total_distance, elapsed]
            if isinstance(metrics, (list, tuple)) and len(metrics) == 4:
                records.append({
                    "Maze Name": maze_name,
                    "Username": user_row["username"],
                    "Score": metrics[0],
                    "Moves": metrics[1],
                    "Distance": metrics[2],
                    "Time (s)": metrics[3],
                })
    return pd.DataFrame(records)


# =====================================================================
#  Tabs
# =====================================================================
def tab_overall(df, season_name):
    render_podium(df)
    st.markdown("&nbsp;", unsafe_allow_html=True)

    search = st.text_input("🔎 Find a player", placeholder="Type a username...")

    view = df[[
        "Rank", "username", "Total Score", "Mazes Completed",
        "Total Moves", "Total Distance (units)", "Total Time (s)",
    ]].rename(columns={"username": "Player"})

    if search:
        view = view[view["Player"].str.contains(search, case=False, na=False)]

    max_score = float(df["Total Score"].max()) or 1.0
    show_df(
        view,
        column_config={
            "Total Score": st.column_config.ProgressColumn(
                "Total Score", format="%.2f", min_value=0, max_value=max_score
            ),
            "Total Distance (units)": st.column_config.NumberColumn(format="%d"),
            "Total Time (s)": st.column_config.NumberColumn(format="%.1f"),
        },
    )
    st.caption(f"Ranked by total score across all mazes · {season_name}")

    st.markdown("##### Top 10 scores")
    st.bar_chart(df.head(10).set_index("username")["Total Score"])


def tab_mazes(df, is_all_time):
    if is_all_time:
        st.info("Per-maze details aren't available in the All-Time view. Pick a single season.")
        return

    maze_df = build_maze_records(df)
    if maze_df.empty:
        st.info("No detailed maze scores available yet.")
        return

    st.markdown("##### Maze overview")
    overview = (
        maze_df.sort_values("Score", ascending=False)
        .groupby("Maze Name")
        .agg(
            Players=("Username", "count"),
            **{"Avg Score": ("Score", "mean"), "Best Score": ("Score", "max")},
            **{"Best Player": ("Username", "first")},
        )
        .reset_index()
        .sort_values("Maze Name")
    )
    show_df(
        overview,
        column_config={
            "Avg Score": st.column_config.NumberColumn(format="%.2f"),
            "Best Score": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    st.markdown("##### Maze ranking")
    selected = st.selectbox(
        "Select a maze", options=sorted(maze_df["Maze Name"].unique())
    )
    ranked = (
        maze_df[maze_df["Maze Name"] == selected]
        .sort_values(["Score", "Time (s)"], ascending=[False, True])
        .reset_index(drop=True)
    )
    ranked.insert(0, "Rank", ranked.index + 1)

    show_df(
        ranked[["Rank", "Username", "Score", "Time (s)", "Moves", "Distance"]],
        column_config={
            "Score": st.column_config.NumberColumn(format="%.2f"),
            "Time (s)": st.column_config.NumberColumn(format="%.2f"),
            "Distance": st.column_config.NumberColumn(format="%.0f"),
        },
    )
    st.bar_chart(ranked.head(10).set_index("Username")["Score"])


def tab_player(df, is_all_time):
    selected = st.selectbox(
        "Select a player",
        options=sorted(df["username"].tolist(), key=str.lower),
        index=None,
        placeholder="Choose a player...",
    )
    if not selected:
        st.caption("Pick a player to see their full breakdown.")
        return

    row = df[df["username"] == selected].iloc[0]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Rank", f"#{int(row['_rank'])}")
    c2.metric("Total Score", f"{row['Total Score']:.2f}")
    c3.metric("Mazes Completed", int(row["Mazes Completed"]))
    c4.metric("Total Moves", f"{int(row['Total Moves']):,}")
    c5.metric("Total Time", f"{row['Total Time (s)']:.1f}s")

    if is_all_time:
        st.info("Per-maze history isn't available in the All-Time view.")
        return

    history = []
    for maze_name, metrics in (row["mazes"] or {}).items():
        if isinstance(metrics, (list, tuple)) and len(metrics) == 4:
            history.append({
                "Maze Name": maze_name,
                "Score": metrics[0],
                "Time (s)": metrics[3],
                "Moves": metrics[1],
                "Distance": metrics[2],
            })

    if not history:
        st.info(f"{selected} has no detailed maze history.")
        return

    history_df = pd.DataFrame(history).sort_values("Score", ascending=False)
    st.markdown("##### Score per maze")
    st.bar_chart(history_df.set_index("Maze Name")["Score"])
    show_df(
        history_df,
        column_config={
            "Score": st.column_config.NumberColumn(format="%.2f"),
            "Time (s)": st.column_config.NumberColumn(format="%.2f"),
            "Distance": st.column_config.NumberColumn(format="%.0f"),
        },
    )


def tab_champions(season_list):
    rows = []
    for s in season_list:
        if s["status"] == "upcoming" or s.get("type") == "casual":
            continue
        champ = fetch_champion(s["id"])
        if champ:
            rows.append({
                "Season": s["name"],
                "Status": STATUS_LABELS.get(s["status"], s["status"]),
                **champ,
            })

    if not rows:
        st.info("No champions yet.")
        return

    show_df(
        pd.DataFrame(rows),
        column_config={"Score": st.column_config.NumberColumn(format="%.2f")},
    )
    st.caption("Leader of each season (final winner for completed seasons).")


# =====================================================================
#  Main app
# =====================================================================
seasons_data, seasons_error = fetch_seasons()

if seasons_error or not seasons_data:
    st.error(seasons_error or "No season data returned.")
    st.caption("If the server was asleep (free hosting), wait ~30s and retry.")
    if st.button("Retry"):
        st.cache_data.clear()
        st.rerun()
    st.stop()

season_list = sorted(
    seasons_data.get("seasons", []), key=lambda s: s.get("number", 0), reverse=True
)
season_by_id = {s["id"]: s for s in season_list}
option_ids = [s["id"] for s in season_list] + ["all"]


def season_label(sid):
    if sid == "all":
        return "🌍 All-Time (competitions only)"
    s = season_by_id[sid]
    icon = "🎮 " if s.get("type") == "casual" else ""
    return f"{icon}{s['name']}  ·  {STATUS_LABELS.get(s['status'], s['status'])}"


current = seasons_data.get("current")
default_index = option_ids.index(current) if current in option_ids else 0

# ---------- Sidebar ----------
with st.sidebar:
    st.header("⚙️ Options")
    selected_season = st.selectbox(
        "Season",
        options=option_ids,
        index=default_index,
        format_func=season_label,
    )
    auto_refresh = st.toggle(f"Auto-refresh every {REFRESH_SECONDS}s", value=True)
    if st.button("🔄 Refresh now"):
        st.cache_data.clear()
        st.rerun()

is_all_time = selected_season == "all"
season_info = season_by_id.get(selected_season, {})
season_name = "All-Time" if is_all_time else season_info.get("name", selected_season)
season_status = "all" if is_all_time else season_info.get("status", "completed")

is_casual = season_info.get("type") == "casual"
if is_all_time:
    badge_text = "🌍 All competition seasons combined"
elif is_casual:
    badge_text = "🎮 Casual play"
else:
    badge_text = STATUS_LABELS.get(season_status, "")

# ---------- Header ----------
st.markdown(
    f"""
    <div class="hero">
        <h1>🐢 Escape Protocol
            <span class="badge">{html.escape(season_name)} · {html.escape(badge_text)}</span>
        </h1>
        <p>Good luck coding!</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if is_casual:
    st.info("🎮 Casual play: scores here are just for fun and don't count toward the competition.")

# ---------- Data ----------
df, error = fetch_leaderboard(selected_season)

if error:
    st.error(error)
    if st.button("Retry fetch"):
        st.cache_data.clear()
        st.rerun()
    st.stop()

tab_labels = ["🏆 Leaderboard", "🗺️ Mazes", "👤 Players", "👑 Champions"]

if df.empty:
    if season_status == "upcoming":
        st.info(f"⏳ {season_name} hasn't started yet. Check back soon!")
    else:
        st.info("No scores submitted yet. Be the first to finish a maze!")
    t1, t2, t3, t4 = st.tabs(tab_labels)
    with t4:
        tab_champions(season_list)
else:
    # Summary cards
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Players", len(df))
    m2.metric("Top Score", f"{df['Total Score'].max():.2f}")
    m3.metric("Mazes Completed", f"{int(df['Mazes Completed'].sum()):,}")
    m4.metric("Total Moves", f"{int(df['Total Moves'].sum()):,}")

    st.markdown("&nbsp;", unsafe_allow_html=True)

    t1, t2, t3, t4 = st.tabs(tab_labels)
    with t1:
        tab_overall(df, season_name)
    with t2:
        tab_mazes(df, is_all_time)
    with t3:
        tab_player(df, is_all_time)
    with t4:
        tab_champions(season_list)

st.caption(f"Last updated: {time.strftime('%H:%M:%S', time.localtime())}")

# Auto-refresh only makes sense for a live season
if auto_refresh and season_status == "active":
    time.sleep(REFRESH_SECONDS)
    st.rerun()
