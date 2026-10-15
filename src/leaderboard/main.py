import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import pandas as pd

#RUN : streamlit run src/leaderboard/main.py

# --- Firebase Setup ---
# When deploying on Streamlit Cloud, use st.secrets instead of local file
if not firebase_admin._apps:
    try:
        # Local file path for development (replace with your actual path if needed)
        cred = credentials.Certificate(r"src\leaderboard\escape-protocol-leaderboard-firebase.json")
        firebase_admin.initialize_app(cred)
    except:
        # Use st.secrets for deployment on Streamlit Cloud
        # You need to configure a secret named 'firebase' with your service account JSON
        try:
            cred = credentials.Certificate(st.secrets["firebase"])
            firebase_admin.initialize_app(cred)
        except Exception as e:
            st.error(f"Could not initialize Firebase. Check your 'firebase.json' path or 'st.secrets': {e}")
            st.stop() # Stop execution if Firebase setup fails

db = firestore.client()
scores_ref = db.collection("leaderboard")

# --- Streamlit UI ---
st.set_page_config(page_title="Escape Protocol Leaderboard", page_icon="🏆", layout="centered")

st.title("🏆 Escape Protocol Leaderboard")

# Submit new score / update existing score
with st.form("score_form", clear_on_submit=True):
    st.subheader("Submit Your Score")
    username = st.text_input("Enter your name:").strip()
    score = st.number_input("Enter your score:", min_value=0.0)
    submit = st.form_submit_button("Submit")

    if submit and username:
        
        # 1. Search for an existing score by this username
        query = scores_ref.where("username", "==", username).limit(1).get()

        new_doc_data = {
            "username": username,
            "score": score,
            "timestamp": datetime.now()
        }

        if query:
            # A record exists! Get the first document's ID
            existing_doc = query[0]
            
            # Check if the new score is an improvement
            existing_score = existing_doc.to_dict().get("score", 0.0)

            if score > existing_score:
                # 2. Update the existing record with the new score and timestamp
                scores_ref.document(existing_doc.id).update(new_doc_data)
                st.success(f"🎉 **High Score!** Record updated for {username} with a score of {score:.2f}!")
                st.rerun()
            else:
                st.info(f"Keep trying, {username}. Your current best score is {existing_score:.2f}.")

        else:
            # 3. No record found, so create a new one
            scores_ref.add(new_doc_data)
            st.success(f"✅ Score submitted successfully for {username}!")
            st.rerun()

# Fetch and display leaderboard
st.divider()
st.subheader("Top Scores")

# Fetch all scores and sort them locally (for simplicity, but consider server-side sorting for large datasets)
try:
    docs = scores_ref.stream()
    data = []
    for d in docs:
        doc_data = d.to_dict()
        data.append({
            "Username": doc_data.get("username", "N/A"),
            "Score": doc_data.get("score", 0.0),
            "Date": doc_data.get("timestamp", datetime.min).strftime("%Y-%m-%d %H:%M:%S")
        })
    
    if data:
        df = pd.DataFrame(data).sort_values(by="Score", ascending=False).reset_index(drop=True)
        st.dataframe(df, width="stretch")
    else:
        st.info("No scores yet. Be the first to play!")

except Exception as e:
    st.error(f"Error fetching leaderboard data: {e}")