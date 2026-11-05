import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, Response, request, jsonify
from functools import wraps
import hmac
import json
import os
import re
import sys
import time

# =====================================================================
#  Firebase initialisation
# =====================================================================
db = None

try:
    firebase_config_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")

    if firebase_config_json:
        service_account_info = json.loads(firebase_config_json)

        if not firebase_admin._apps:
            cred = credentials.Certificate(service_account_info)
            firebase_admin.initialize_app(cred)

        db = firestore.client()
        print("INFO: Firebase initialized securely.", file=sys.stderr)
    else:
        print("CRITICAL: FIREBASE_CREDENTIALS_JSON not found. DB connection failed.", file=sys.stderr)

except Exception as e:
    print(f"FATAL ERROR during Firebase init: {e}", file=sys.stderr)

app = Flask(__name__)

# ---------------------------------------------------------------------
#  Environment variables (set these in the Render dashboard)
#    ADMIN_KEY          secret used to unlock the admin panel / admin API
#    PROTECTED_SEASONS  comma-separated season ids that can never be deleted
#                       through the admin API (default: season_1)
# ---------------------------------------------------------------------
ADMIN_KEY = os.environ.get("ADMIN_KEY")
PROTECTED_SEASONS = {
    s.strip() for s in os.environ.get("PROTECTED_SEASONS", "season_1").split(",") if s.strip()
}

SEASON_ID_PATTERN = re.compile(r"[a-z0-9_]{1,40}")
VALID_STATUSES = {"upcoming", "active", "completed"}
# "competition" seasons are ranked and count toward champions / all-time.
# "casual" seasons accept scores but never count toward the competition.
VALID_TYPES = {"competition", "casual"}

# =====================================================================
#  Firestore layout
#
#  seasons/{season_id}                      { name, number, status }
#  seasons/{season_id}/leaderboard/{user}   { total, mazes, total_moves,
#                                             total_distance, total_time,
#                                             last_updated }
# =====================================================================


# =====================================================================
#  Helpers
# =====================================================================
def season_lb(season_id):
    """Leaderboard sub-collection for a given season."""
    return db.collection("seasons").document(season_id).collection("leaderboard")


def valid_season_id(season_id):
    return bool(season_id) and SEASON_ID_PATTERN.fullmatch(season_id) is not None


def get_current_season_id():
    """Newest active season (highest 'number'). None if no season is active."""
    best_id, best_num = None, -1
    for d in db.collection("seasons").where("status", "==", "active").stream():
        sd = d.to_dict() or {}
        if sd.get("type", "competition") == "casual":
            continue
        num = sd.get("number", 0)
        if num >= best_num:
            best_id, best_num = d.id, num
    return best_id


def get_latest_season_id():
    """Newest season of any status (display fallback between seasons)."""
    best_id, best_num = None, -1
    for d in db.collection("seasons").stream():
        sd = d.to_dict() or {}
        if sd.get("type", "competition") == "casual":
            continue
        num = sd.get("number", 0)
        if num >= best_num:
            best_id, best_num = d.id, num
    return best_id


def count_players(season_id):
    try:
        res = season_lb(season_id).count().get()
        return int(res[0][0].value)
    except Exception:
        return sum(1 for _ in season_lb(season_id).stream())


def next_season_number():
    nums = []
    for d in db.collection("seasons").stream():
        sd = d.to_dict() or {}
        if sd.get("type", "competition") != "casual":
            nums.append(sd.get("number", 0))
    return max(nums + [0]) + 1


def delete_season_data(season_id):
    ref = db.collection("seasons").document(season_id)
    while True:
        docs = list(ref.collection("leaderboard").limit(400).stream())
        if not docs:
            break
        batch = db.batch()
        for d in docs:
            batch.delete(d.reference)
        batch.commit()
    ref.delete()


# =====================================================================
#  Admin authentication
#
#  The admin key is a shared secret. The client sends it in the
#  X-Admin-Key header; the server compares it (constant time) with the
#  ADMIN_KEY environment variable. If ADMIN_KEY isn't set, admin is
#  disabled entirely. Repeated wrong guesses get temporarily blocked.
# =====================================================================
_failed_attempts = {}   # ip -> [timestamps]   (in-memory, resets on restart)
MAX_FAILS = 5
FAIL_WINDOW_SECONDS = 600


def client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or "unknown"


def check_admin():
    """Returns None if authorised, otherwise a (response, status) tuple."""
    if not ADMIN_KEY:
        return jsonify({"error": "Admin is disabled: ADMIN_KEY is not set on the server."}), 503

    ip = client_ip()
    now = time.time()
    recent = [t for t in _failed_attempts.get(ip, []) if now - t < FAIL_WINDOW_SECONDS]

    if len(recent) >= MAX_FAILS:
        _failed_attempts[ip] = recent
        return jsonify({"error": "Too many failed attempts. Try again in a few minutes."}), 429

    provided = request.headers.get("X-Admin-Key", "")
    if not hmac.compare_digest(provided.encode("utf-8"), ADMIN_KEY.encode("utf-8")):
        recent.append(now)
        _failed_attempts[ip] = recent
        return jsonify({"error": "Invalid admin key."}), 403

    _failed_attempts.pop(ip, None)
    return None


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        denied = check_admin()
        if denied:
            return denied
        if not db:
            return jsonify({"error": "Server not connected to Database."}), 503
        return fn(*args, **kwargs)
    return wrapper


# =====================================================================
#  Game / public endpoints
# =====================================================================
@app.route("/submit_score", methods=["POST"])
def submit_score():
    """
    Receives individual maze metrics and updates the user's totals inside
    the requested season.

    Payload:
      username, score, moves, distance, time_elapsed,
      season (optional - falls back to the current active season),
      maze_scores: {"Maze Name": [score, moves, distance, time_elapsed]}
    """
    if not db:
        return jsonify({"error": "Server not connected to Database."}), 503

    # ---------- Parse & validate payload ----------
    try:
        data = request.get_json(silent=True) or {}
        username = (data.get("username") or "").strip()

        score = data.get("score")
        moves = data.get("moves", 0)
        distance = data.get("distance", 0.0)
        time_elapsed = data.get("time_elapsed", 0.0)
        maze_scores = data.get("maze_scores", {})

        if not username or score is None:
            return jsonify({"error": "Missing username or score"}), 400

        # Firestore document ids cannot contain '/' and must not be '.' / '..'
        if "/" in username or username in (".", "..") or len(username) > 100:
            return jsonify({"error": "Invalid username."}), 400

        if not isinstance(maze_scores, dict):
            return jsonify({"error": "Invalid maze_scores."}), 400

        # Derive time from per-maze data (older clients never sent time_elapsed)
        if maze_scores:
            first_metrics = list(maze_scores.values())[0]
            if not isinstance(first_metrics, (list, tuple)) or len(first_metrics) != 4:
                return jsonify({"error": "maze_scores entries must be [score, moves, distance, time]."}), 400
            time_elapsed = first_metrics[3]

        moves_int = int(moves) if moves is not None else 0
        distance_float = float(distance) if distance is not None else 0.0
        time_float = float(time_elapsed) if time_elapsed is not None else 0.0
        score_float = float(score)

    except (ValueError, TypeError) as e:
        print(f"Validation Error: {e}", file=sys.stderr)
        return jsonify({"error": "Invalid data format or type received."}), 400

    # ---------- Resolve & validate season ----------
    season_id = (data.get("season") or "").strip()
    if not season_id:
        season_id = get_current_season_id()   # fallback for old clients

    if not season_id or not valid_season_id(season_id):
        return jsonify({"error": "Invalid season."}), 400

    season_snapshot = db.collection("seasons").document(season_id).get()
    if not season_snapshot.exists:
        return jsonify({"error": "Unknown season."}), 404
    if (season_snapshot.to_dict() or {}).get("status") != "active":
        return jsonify({"error": "Season is closed."}), 403

    # ---------- Load user's record for this season ----------
    user_ref = season_lb(season_id).document(username)

    user_data = user_ref.get().to_dict() or {
        "total": 0.0,
        "mazes": {},
        "total_moves": 0,
        "total_distance": 0.0,
        "total_time": 0.0,
    }
    user_data.setdefault("mazes", {})

    # ---------- Replay adjustment: remove the old attempt first ----------
    maze_name = list(maze_scores.keys())[0] if maze_scores else None
    old_maze_data = user_data["mazes"].get(maze_name) if maze_name else None

    if old_maze_data and len(old_maze_data) == 4:
        old_score, old_moves, old_distance, old_time = old_maze_data
        user_data["total"] = user_data.get("total", 0.0) - old_score
        user_data["total_moves"] = user_data.get("total_moves", 0) - old_moves
        user_data["total_distance"] = user_data.get("total_distance", 0.0) - old_distance
        user_data["total_time"] = user_data.get("total_time", 0.0) - old_time

    # ---------- Add the new attempt ----------
    user_data["total"] = user_data.get("total", 0.0) + score_float
    user_data["total_moves"] = user_data.get("total_moves", 0) + moves_int
    user_data["total_distance"] = user_data.get("total_distance", 0.0) + distance_float
    user_data["total_time"] = user_data.get("total_time", 0.0) + time_float

    user_data["mazes"].update(maze_scores)
    user_data["last_updated"] = firestore.SERVER_TIMESTAMP

    user_ref.set(user_data)

    return jsonify({
        "message": "Score and all metrics updated",
        "season": season_id,
        "user_total": user_data["total"],
        "total_moves": user_data["total_moves"],
    }), 200


@app.route("/seasons", methods=["GET"])
def seasons():
    """Lists all seasons and which one is currently active."""
    if not db:
        return jsonify({"error": "Server not connected to Database."}), 503

    try:
        items = []
        for d in db.collection("seasons").stream():
            sd = d.to_dict() or {}
            items.append({
                "id": d.id,
                "name": sd.get("name", d.id),
                "number": sd.get("number", 0),
                "status": sd.get("status", "upcoming"),
                "type": sd.get("type", "competition"),
            })
        items.sort(key=lambda s: (s["number"], s["id"]))

        current = get_current_season_id() or get_latest_season_id()
        return jsonify({"current": current, "seasons": items}), 200
    except Exception as e:
        print(f"Seasons retrieval error: {e}", file=sys.stderr)
        return jsonify({"error": "Failed to retrieve seasons."}), 500


@app.route("/leaderboard", methods=["GET"])
def leaderboard():
    """
    GET /leaderboard                  -> current season
    GET /leaderboard?season=season_1  -> that season
    GET /leaderboard?season=all       -> all-time (summed across seasons)
    """
    if not db:
        return jsonify({"error": "Server not connected to Database."}), 503

    try:
        season_id = (request.args.get("season") or "").strip()
        if not season_id:
            season_id = get_current_season_id() or get_latest_season_id()

        if not season_id:
            return jsonify([]), 200

        # ---------- All-time ----------
        if season_id == "all":
            totals = {}
            for s in db.collection("seasons").stream():
                if (s.to_dict() or {}).get("type", "competition") == "casual":
                    continue
                for doc in season_lb(s.id).stream():
                    d = doc.to_dict() or {}
                    t = totals.setdefault(doc.id, {
                        "username": doc.id,
                        "total": 0.0,
                        "total_moves": 0,
                        "total_distance": 0.0,
                        "total_time": 0.0,
                        "mazes_completed": 0,
                        "mazes": {},
                    })
                    t["total"] += d.get("total", 0.0)
                    t["total_moves"] += d.get("total_moves", 0)
                    t["total_distance"] += d.get("total_distance", 0.0)
                    t["total_time"] += d.get("total_time", 0.0)
                    t["mazes_completed"] += len(d.get("mazes", {}))
            data = sorted(totals.values(), key=lambda x: x["total"], reverse=True)
            return jsonify(data), 200

        # ---------- Single season ----------
        if not valid_season_id(season_id):
            return jsonify({"error": "Invalid season."}), 400

        docs = season_lb(season_id).order_by(
            "total", direction=firestore.Query.DESCENDING
        ).stream()

        leaderboard_data = []
        for doc in docs:
            d = doc.to_dict() or {}
            leaderboard_data.append({
                "username": doc.id,
                "total": d.get("total", 0.0),
                "total_moves": d.get("total_moves", 0),
                "total_distance": d.get("total_distance", 0.0),
                "total_time": d.get("total_time", 0.0),
                "mazes_completed": len(d.get("mazes", {})),
                "mazes": d.get("mazes", {}),
            })

        return jsonify(leaderboard_data), 200

    except Exception as e:
        print(f"Leaderboard retrieval error: {e}", file=sys.stderr)
        return jsonify({"error": "Failed to retrieve leaderboard data."}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "db": db is not None}), 200


# =====================================================================
#  Admin API  (all require the X-Admin-Key header)
# =====================================================================
@app.route("/admin/api/seasons", methods=["GET"])
@admin_required
def admin_list_seasons():
    """All seasons with player counts. Also used by the panel to check the key."""
    items = []
    for d in db.collection("seasons").stream():
        sd = d.to_dict() or {}
        items.append({
            "id": d.id,
            "name": sd.get("name", d.id),
            "number": sd.get("number", 0),
            "status": sd.get("status", "upcoming"),
            "type": sd.get("type", "competition"),
            "players": count_players(d.id),
            "protected": d.id in PROTECTED_SEASONS,
        })
    items.sort(key=lambda s: (s["number"], s["id"]), reverse=True)
    return jsonify({
        "current": get_current_season_id(),
        "next_number": next_season_number(),
        "seasons": items,
    }), 200


@app.route("/admin/season", methods=["POST"])
@admin_required
def admin_season():
    """
    Create or update a season.

    Everything is optional, so these all work:
      {}                                   -> creates the next season (upcoming)
      {"number": 3}                        -> creates season_3 "Season 3"
      {"id": "season_2", "status": "active"}              -> go live
      {"id": "season_2", "status": "active", "close_others": true}
                                           -> go live and close every other active season
      {"id": "season_2", "status": "completed"}           -> close it
      {"id": "test_season", "name": "Test", "number": 0, "status": "active"}
    """
    d = request.get_json(silent=True) or {}
    sid = (d.get("id") or "").strip()

    number = None
    if d.get("number") not in (None, ""):
        try:
            number = int(d["number"])
        except (ValueError, TypeError):
            return jsonify({"error": "number must be an integer."}), 400

    season_type = d.get("type")
    if season_type is not None and season_type not in VALID_TYPES:
        return jsonify({"error": f"type must be one of {sorted(VALID_TYPES)}."}), 400
    if season_type == "casual" and number is None:
        number = 0

    if not sid:
        if season_type == "casual":
            sid = "casual"
        else:
            if number is None:
                number = next_season_number()
            sid = f"season_{number}"

    if not valid_season_id(sid):
        return jsonify({"error": "Bad id (use a-z, 0-9, underscore; max 40 chars)."}), 400

    ref = db.collection("seasons").document(sid)
    snap = ref.get()
    is_new = not snap.exists
    existing_type = (snap.to_dict() or {}).get("type", "competition") if snap.exists else "competition"
    effective_type = season_type or existing_type

    if is_new and number is None:
        number = 0 if effective_type == "casual" else next_season_number()

    fields = {}
    if number is not None:
        fields["number"] = number

    name = str(d.get("name") or "").strip()
    if name:
        fields["name"] = name[:100]
    elif is_new:
        fields["name"] = "Casual Play" if effective_type == "casual" else f"Season {number}"

    if season_type is not None or is_new:
        fields["type"] = effective_type

    if "status" in d:
        if d["status"] not in VALID_STATUSES:
            return jsonify({"error": f"status must be one of {sorted(VALID_STATUSES)}."}), 400
        fields["status"] = d["status"]
    elif is_new:
        fields["status"] = "upcoming"

    if not fields:
        return jsonify({"error": "Nothing to update."}), 400

    closed_others = []
    if fields.get("status") == "active" and d.get("close_others") and effective_type == "competition":
        for s in db.collection("seasons").where("status", "==", "active").stream():
            other_type = (s.to_dict() or {}).get("type", "competition")
            if s.id != sid and other_type == "competition":
                s.reference.set({"status": "completed"}, merge=True)
                closed_others.append(s.id)

    ref.set(fields, merge=True)
    return jsonify({
        "ok": True,
        "created": is_new,
        "season": sid,
        "closed_others": closed_others,
        **fields,
    }), 200


@app.route("/admin/season/delete", methods=["POST"])
@admin_required
def admin_delete_season():
    """
    Permanently delete a season and all its scores.
      {"id": "test_season", "confirm": "test_season"}
    Rules: protected seasons can't be deleted; active seasons must be closed
    first; completed seasons with players also need "force": true.
    """
    d = request.get_json(silent=True) or {}
    sid = (d.get("id") or "").strip()

    if not valid_season_id(sid):
        return jsonify({"error": "Bad id."}), 400
    if d.get("confirm") != sid:
        return jsonify({"error": "Send \"confirm\" equal to the season id to delete it."}), 400
    if sid in PROTECTED_SEASONS:
        return jsonify({"error": f"'{sid}' is protected and cannot be deleted."}), 403

    snap = db.collection("seasons").document(sid).get()
    if not snap.exists:
        return jsonify({"error": "Unknown season."}), 404

    status = (snap.to_dict() or {}).get("status")
    if status == "active":
        return jsonify({"error": "Season is active. Close it first."}), 409

    players = count_players(sid)
    if status == "completed" and players > 0 and not d.get("force"):
        return jsonify({
            "error": f"'{sid}' is completed and has {players} players. Send \"force\": true to delete it."
        }), 409

    delete_season_data(sid)
    return jsonify({"ok": True, "deleted": sid, "players_removed": players}), 200


@app.route("/admin/export", methods=["GET"])
@admin_required
def admin_export():
    """Download a season (meta + all player records) as JSON: /admin/export?season=season_1"""
    sid = (request.args.get("season") or "").strip()
    if not valid_season_id(sid):
        return jsonify({"error": "Bad season id."}), 400

    snap = db.collection("seasons").document(sid).get()
    if not snap.exists:
        return jsonify({"error": "Unknown season."}), 404

    payload = {
        "season": sid,
        "meta": snap.to_dict(),
        "leaderboard": {d.id: d.to_dict() for d in season_lb(sid).stream()},
    }
    body = json.dumps(payload, default=str, indent=2)
    return Response(
        body,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{sid}_export.json"'},
    )


# =====================================================================
#  Admin web panel  ->  open  https://<your-server>/admin
#  The page itself is public HTML with no data in it; every action calls
#  the admin API above using the key you type in.
# =====================================================================
ADMIN_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Escape Protocol - Admin</title>
<style>
  :root { --bg:#f4f6fb; --card:#fff; --text:#0f172a; --muted:#64748b; --line:#e2e8f0;
          --brand:#1e40af; --ok:#15803d; --err:#b91c1c; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0b1220; --card:#131c2e; --text:#e5e9f2; --muted:#94a3b8; --line:#243049;
            --brand:#60a5fa; --ok:#4ade80; --err:#f87171; }
  }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         background:var(--bg); color:var(--text); }
  .wrap { max-width: 920px; margin: 0 auto; padding: 24px 16px 60px; }
  h1 { margin: 0 0 4px; font-size: 1.6rem; }
  .sub { color: var(--muted); font-size: .85rem; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px;
          padding:18px; margin-top:16px; }
  h2 { margin:0 0 12px; font-size:1.05rem; }
  input, select, button { font: inherit; }
  input, select { padding:9px 11px; border:1px solid var(--line); border-radius:9px;
                  background:var(--bg); color:var(--text); }
  button { padding:8px 12px; border:1px solid var(--line); border-radius:9px;
           background:var(--card); color:var(--text); cursor:pointer; }
  button:hover { border-color: var(--brand); }
  button.primary { background:var(--brand); color:#fff; border-color:var(--brand); }
  button.danger { color:var(--err); }
  button:disabled { opacity:.4; cursor:not-allowed; }
  table { width:100%; border-collapse:collapse; }
  th { text-align:left; font-size:.75rem; text-transform:uppercase; color:var(--muted);
       padding:6px 8px; border-bottom:1px solid var(--line); }
  td { padding:10px 8px; border-bottom:1px solid var(--line); vertical-align:middle; }
  .actions { display:flex; flex-wrap:wrap; gap:6px; }
  .badge { padding:2px 10px; border-radius:999px; font-size:.78rem; font-weight:600; }
  .badge.active { background:#dcfce7; color:#166534; }
  .badge.completed { background:#e2e8f0; color:#334155; }
  .badge.upcoming { background:#fef3c7; color:#92400e; }
  .row { display:flex; flex-wrap:wrap; gap:10px; align-items:center; }
  #msg { margin-top:14px; padding:10px 12px; border-radius:9px; display:none; font-size:.9rem; }
  #msg.ok { display:block; background:rgba(34,197,94,.15); color:var(--ok); }
  #msg.err { display:block; background:rgba(239,68,68,.15); color:var(--err); }
  label.check { display:flex; gap:6px; align-items:center; font-size:.9rem; color:var(--muted); }
  .scroll { overflow-x:auto; }
</style>
</head>
<body>
<div class="wrap">
  <h1>🐢 Escape Protocol &mdash; Admin</h1>
  <div class="sub">Manage competition seasons</div>

  <div id="msg"></div>

  <div id="login" class="card">
    <h2>Sign in</h2>
    <div class="row">
      <input id="key" type="password" placeholder="Admin key" autocomplete="off" style="flex:1;min-width:220px">
      <button id="loginBtn" class="primary">Unlock</button>
    </div>
  </div>

  <div id="panel" hidden>
    <div class="card">
      <div class="row" style="justify-content:space-between">
        <h2 style="margin:0">Seasons</h2>
        <div class="row">
          <label class="check"><input type="checkbox" id="closeOthers" checked>
            Close other live seasons when going live</label>
          <button id="refreshBtn">Refresh</button>
          <button id="logoutBtn">Sign out</button>
        </div>
      </div>
      <div class="scroll" style="margin-top:10px">
        <table>
          <thead><tr><th>Season</th><th>Status</th><th>Players</th><th>Actions</th></tr></thead>
          <tbody id="rows"></tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <h2>Create a new season</h2>
      <div class="row">
        <input id="newName" placeholder="Name (e.g. Season 3)" style="flex:1;min-width:200px">
        <input id="newNumber" type="number" min="0" placeholder="Number (auto)" style="width:140px">
        <select id="newType">
          <option value="competition">Competition season</option>
          <option value="casual">Casual play (no competition)</option>
        </select>
        <select id="newStatus">
          <option value="upcoming">Start as upcoming</option>
          <option value="active">Start live now</option>
        </select>
        <button id="createBtn" class="primary">Create</button>
      </div>
      <div class="sub" style="margin-top:8px">
        Leave name and number empty to create the next season automatically.
        Use number 0 for a test season so it never becomes the default.
      </div>
    </div>
  </div>
</div>

<script>
  const label = { active: "Live", completed: "Completed", upcoming: "Upcoming" };
  let KEY = sessionStorage.getItem("adminKey") || "";
  let seasons = [];

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function toast(text, ok = true) {
    const m = $("msg");
    m.textContent = text;
    m.className = ok ? "ok" : "err";
    clearTimeout(toast.t);
    toast.t = setTimeout(() => { m.className = ""; }, 6000);
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      ...opts,
      headers: { "X-Admin-Key": KEY, "Content-Type": "application/json" },
    });
    if (!res.ok) {
      let err = res.statusText;
      try { err = (await res.json()).error || err; } catch (e) {}
      throw new Error(err);
    }
    return res;
  }

  function showPanel(on) {
    $("login").hidden = on;
    $("panel").hidden = !on;
  }

  async function load() {
    const res = await api("/admin/api/seasons");
    const data = await res.json();
    seasons = data.seasons;
    $("newNumber").placeholder = "Number (auto: " + data.next_number + ")";
    $("rows").innerHTML = seasons.map(rowHtml).join("") ||
      '<tr><td colspan="4" class="sub">No seasons yet.</td></tr>';
  }

  function rowHtml(s) {
    const btn = (a, text, extra = "", cls = "") =>
      `<button class="${cls}" data-a="${a}" data-id="${esc(s.id)}" ${extra}>${text}</button>`;
    let b = "";
    if (s.status !== "active") b += btn("status", "▶ Go live", 'data-s="active"');
    if (s.status === "active") b += btn("status", "⏹ Close", 'data-s="completed"');
    if (s.status !== "upcoming" && s.status !== "active")
      b += btn("status", "↩ Set upcoming", 'data-s="upcoming"');
    b += btn("export", "⬇ Export");
    b += btn("delete", "🗑 Delete", s.protected ? "disabled title='Protected season'" : "", "danger");
    return `<tr>
      <td><b>${esc(s.name)}</b><div class="sub">${esc(s.id)} · ${s.type === "casual" ? "🎮 casual" : "#" + esc(s.number)}${s.protected ? " · 🔒 protected" : ""}</div></td>
      <td><span class="badge ${esc(s.status)}">${esc(label[s.status] || s.status)}</span></td>
      <td>${esc(s.players)}</td>
      <td><div class="actions">${b}</div></td>
    </tr>`;
  }

  async function login() {
    KEY = $("key").value.trim();
    if (!KEY) return;
    try {
      await load();
      sessionStorage.setItem("adminKey", KEY);
      $("key").value = "";
      showPanel(true);
    } catch (e) {
      KEY = "";
      toast(e.message, false);
    }
  }

  function logout() {
    sessionStorage.removeItem("adminKey");
    KEY = "";
    showPanel(false);
  }

  async function setStatus(id, status) {
    const s = seasons.find((x) => x.id === id);
    if (status === "completed" &&
        !confirm(`Close "${s.name}"? Players will no longer be able to submit scores.`)) return;
    if (status === "active" &&
        !confirm(`Make "${s.name}" live? Players will be able to submit scores to it.`)) return;
    const res = await api("/admin/season", {
      method: "POST",
      body: JSON.stringify({ id, status, close_others: status === "active" && $("closeOthers").checked }),
    });
    const out = await res.json();
    let t = `${s.name} is now ${label[status].toLowerCase()}.`;
    if (out.closed_others && out.closed_others.length) t += ` Closed: ${out.closed_others.join(", ")}.`;
    toast(t);
    await load();
  }

  async function exportSeason(id) {
    const res = await api("/admin/export?season=" + encodeURIComponent(id));
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = id + "_export.json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast(`Exported ${id}.`);
  }

  async function deleteSeason(id) {
    const s = seasons.find((x) => x.id === id);
    let force = false;
    if (s.status === "completed" && s.players > 0) {
      if (prompt(`"${s.name}" is COMPLETED and has ${s.players} players.\nThis permanently deletes all its scores.\nType DELETE to confirm:`) !== "DELETE") return;
      force = true;
    } else if (prompt(`Type the season id (${s.id}) to permanently delete it:`) !== s.id) {
      return;
    }
    const res = await api("/admin/season/delete", {
      method: "POST",
      body: JSON.stringify({ id, confirm: id, force }),
    });
    const out = await res.json();
    toast(`Deleted ${id} (${out.players_removed} players removed).`);
    await load();
  }

  async function createSeason() {
    const body = {};
    if ($("newName").value.trim()) body.name = $("newName").value.trim();
    if ($("newNumber").value !== "") body.number = parseInt($("newNumber").value, 10);
    body.status = $("newStatus").value;
    body.type = $("newType").value;
    if (body.status === "active" && !confirm("Start this season live right away?")) return;
    if (body.status === "active") body.close_others = $("closeOthers").checked;
    const res = await api("/admin/season", { method: "POST", body: JSON.stringify(body) });
    const out = await res.json();
    toast(`Created ${out.name} (${out.season}) as ${out.status}.`);
    $("newName").value = "";
    $("newNumber").value = "";
    await load();
  }

  const guard = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, false); } };

  $("loginBtn").onclick = login;
  $("key").addEventListener("keydown", (e) => { if (e.key === "Enter") login(); });
  $("logoutBtn").onclick = logout;
  $("refreshBtn").onclick = guard(load);
  $("createBtn").onclick = guard(createSeason);
  $("rows").addEventListener("click", guard(async (e) => {
    const b = e.target.closest("button");
    if (!b || b.disabled) return;
    const id = b.dataset.id;
    if (b.dataset.a === "status") await setStatus(id, b.dataset.s);
    else if (b.dataset.a === "export") await exportSeason(id);
    else if (b.dataset.a === "delete") await deleteSeason(id);
  }));

  // Auto sign-in if the key is still in this tab's session
  if (KEY) {
    load().then(() => showPanel(true)).catch(() => { logout(); });
  }
</script>
</body>
</html>
"""


@app.route("/admin", methods=["GET"])
def admin_page():
    resp = Response(ADMIN_PAGE, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)