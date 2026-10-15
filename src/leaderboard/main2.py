import streamlit as st
import pandas as pd
import requests
import json
import time

#RUN : streamlit run src/leaderboard/main2.py


# --- Configuration ---
st.set_page_config(layout="wide", page_title="Escape Protocol")

# NOTE: Replace with your actual deployed Render URL
API_URL = r"https://ace-rnd-escapeprotocol.onrender.com/leaderboard" 

# --- Data Fetching ---
@st.cache_data(ttl=5)
def fetch_leaderboard():
    """Fetches the aggregated leaderboard data from the Flask API."""
    try:
        response = requests.get(API_URL)
        response.raise_for_status()
        data = response.json()
        
        # Ensure 'mazes' is present, even if empty, for robust DataFrame creation
        for entry in data:
            if 'mazes' not in entry:
                entry['mazes'] = {}

        df = pd.DataFrame(data)
        
        # Rename columns for display
        df.rename(columns={
            "total": "Total Score",
            "total_moves": "Total Moves",
            "total_distance": "Total Distance (units)",
            "total_time": "Total Time (s)",
            "mazes_completed": "Mazes Completed"
        }, inplace=True)
        
        # Sort the main DataFrame by Total Score (descending)
        df.sort_values(by="Total Score", ascending=False, inplace=True)
        
        return df, None
    except requests.exceptions.RequestException as e:
        return pd.DataFrame(), f"❌ Error connecting to API: {e}. Check if API is running at {API_URL}"
    except Exception as e:
        return pd.DataFrame(), f"❌ Error processing data: {e}"


# --- Leaderboard Views ---

def display_overall_leaderboard(df):
    """Displays the main leaderboard ranked by Total Score."""
    st.header("🏆 Global Leaderboard")
    st.caption("Ranked by Total Score across all mazes.")
    
    display_df = df.copy().drop(columns=['mazes', 'Total Time (s)'])
    
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_order=["username", "Total Score", "Mazes Completed", "Total Moves", "Total Distance (units)"],
        column_config={
            "Total Score": st.column_config.NumberColumn(format="%.2f"),
            "Total Distance (units)": st.column_config.NumberColumn(format="%d"),
        }
    )

def generate_maze_leaderboard(df):
    """Generates a detailed ranking for each individual maze."""
    st.subheader("🗺️ Per-Maze Leaderboard")
    
    # 1. Prepare list of all unique maze names
    all_mazes = set()
    for index, row in df.iterrows():
        all_mazes.update(row['mazes'].keys())
        
    if not all_mazes:
        st.info("No detailed maze scores available yet.")
        return

    # 2. Iterate and create the single, long DataFrame
    maze_records = []
    for index, user_row in df.iterrows():
        username = user_row['username']
        for maze_name, metrics in user_row['mazes'].items():
            # metrics = [score, move_count, total_distance, elapsed]
            if len(metrics) == 4:
                maze_records.append({
                    "Maze Name": maze_name,
                    "Username": username,
                    "Score": metrics[0],
                    "Moves": metrics[1],
                    "Distance": metrics[2],
                    "Time (s)": metrics[3]
                })

    if not maze_records:
        st.info("No detailed maze score records found.")
        return

    maze_df = pd.DataFrame(maze_records)

    # 3. Display rankings for a selected maze
    selected_maze = st.selectbox(
        "Select a Maze to see its ranking:",
        options=sorted(list(all_mazes))
    )
    
    if selected_maze:
        ranked_maze_df = maze_df[maze_df["Maze Name"] == selected_maze].copy()
        
        # Rank by Score (highest is best)
        ranked_maze_df.sort_values(by="Score", ascending=False, inplace=True)
        
        # Select and format columns for display
        display_cols = ["Username", "Score", "Time (s)", "Moves", "Distance"]
        st.dataframe(
            ranked_maze_df[display_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Score": st.column_config.NumberColumn(format="%.2f"),
                "Distance": st.column_config.NumberColumn(format="%.0f"),
                "Time (s)": st.column_config.NumberColumn(format="%.2f")
            }
        )

def display_user_history(df):
    """Displays the detailed performance history for a selected user."""
    st.subheader("👤 User Performance Detail")
    
    usernames = [""] + sorted(df['username'].tolist())
    selected_user = st.selectbox(
        "Select a User to view their history:",
        options=usernames
    )

    if selected_user and selected_user != "":
        user_data = df[df['username'] == selected_user].iloc[0]
        
        st.markdown(f"**Total Aggregated Performance for {selected_user}:**")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Score", f"{user_data['Total Score']:.2f}")
        col2.metric("Mazes Completed", user_data['Mazes Completed'])
        col3.metric("Total Moves", f"{user_data['Total Moves']:,}")
        col4.metric("Total Time", f"{user_data['Total Time (s)']:.1f}s")
        
        st.markdown("---")
        st.markdown("**Per-Maze History:**")
        
        maze_history = []
        for maze_name, metrics in user_data['mazes'].items():
            # metrics = [score, move_count, total_distance, elapsed]
            if len(metrics) == 4:
                maze_history.append({
                    "Maze Name": maze_name,
                    "Score": metrics[0],
                    "Time (s)": metrics[3],
                    "Moves": metrics[1],
                    "Distance": metrics[2]
                })
        
        if maze_history:
            history_df = pd.DataFrame(maze_history)
            history_df.sort_values(by="Score", ascending=False, inplace=True)
            st.dataframe(
                history_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Score": st.column_config.NumberColumn(format="%.2f"),
                    "Distance": st.column_config.NumberColumn(format="%.0f"),
                    "Time (s)": st.column_config.NumberColumn(format="%.2f")
                }
            )
        else:
            st.info(f"{selected_user} has no detailed maze history.")


# --- Main App Execution ---

st.title("Escape Protocol")
st.markdown("Good Luck Coding")

df, error = fetch_leaderboard()

if error:
    st.error(error)
    # Provide a link to refresh manually if the server was sleeping
    if "Error connecting to API" in error:
        if st.button("Retry Fetch"):
            st.rerun()
else:
    # 1. Display Overall Leaderboard
    display_overall_leaderboard(df)
    
    st.markdown("---")

    # 2. Per-Maze Leaderboard and User History
    col_maze, col_user = st.columns(2)
    
    with col_maze:
        generate_maze_leaderboard(df)

    with col_user:
        display_user_history(df)

    st.caption(f"Last updated: {time.strftime('%H:%M:%S', time.localtime())}")

