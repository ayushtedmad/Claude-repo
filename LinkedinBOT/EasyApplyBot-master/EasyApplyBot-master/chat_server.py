"""
chat_server.py
==============
Flask bridge between the bot process and the browser overlay.

Endpoints
---------
GET  /overlay        - serves chat_overlay.html over HTTP
POST /question       - bot posts a pending question
GET  /question       - browser polls for pending question
POST /answer         - browser sends user's answer
GET  /answer         - bot long-polls for the answer (blocks up to POLL_TIMEOUT s)
POST /pause          - browser pauses the bot
POST /resume         - browser resumes the bot
POST /stop           - browser stops the bot completely
POST /restart        - browser restarts/resumes the bot from stopped state
GET  /status         - returns {paused, stopped, pending_question}
GET  /logs?since=N   - returns new log lines since index N
POST /log            - bot pushes a log line
GET  /ping           - health check
"""

import os
import threading
import time
from collections import deque
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# Serve static files from the same directory as this script
_HERE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=_HERE, static_url_path="")
CORS(app)

# ── Shared state ────────────────────────────────────────────────────────────
_lock = threading.Lock()

# Question / answer state
_pending_question: dict | None = None
_pending_answer:   str  | None = None
_question_event = threading.Event()
_answer_event   = threading.Event()

# Bot control state
_paused        = False
_stopped       = False
_resume_event  = threading.Event()
_resume_event.set()          # start un-paused / un-stopped

# Log buffer — last 500 lines
_log_buffer: deque = deque(maxlen=500)
_log_index   = 0
_log_lock    = threading.Lock()

POLL_TIMEOUT = 180
SERVER_PORT  = 5199


# ── Log helpers ─────────────────────────────────────────────────────────────

def push_log(msg: str, level: str = "INFO"):
    """Push a log entry from the bot into the browser-visible log buffer."""
    global _log_index
    ts = time.strftime("%H:%M:%S")
    with _log_lock:
        entry = {"i": _log_index, "ts": ts, "level": level, "msg": str(msg)}
        _log_buffer.append(entry)
        _log_index += 1


# ── Overlay page ─────────────────────────────────────────────────────────────

@app.route("/overlay")
def serve_overlay():
    return send_from_directory(_HERE, "chat_overlay.html")


# ── Log endpoints ────────────────────────────────────────────────────────────

@app.route("/log", methods=["POST"])
def receive_log():
    data = request.get_json(force=True)
    push_log(data.get("msg", ""), data.get("level", "INFO"))
    return jsonify({"status": "ok"})


@app.route("/logs", methods=["GET"])
def get_logs():
    since = int(request.args.get("since", -1))
    with _log_lock:
        new_entries = [e for e in _log_buffer if e["i"] > since]
    return jsonify({"logs": new_entries})


# ── Question endpoints ────────────────────────────────────────────────────────

@app.route("/question", methods=["POST"])
def receive_question():
    global _pending_question, _pending_answer
    data = request.get_json(force=True)
    with _lock:
        _pending_question = data
        _pending_answer   = None
        _answer_event.clear()
        _question_event.set()
    return jsonify({"status": "ok"})


@app.route("/question", methods=["GET"])
def send_question():
    with _lock:
        q = _pending_question
    return jsonify(q or {})


@app.route("/answer", methods=["GET"])
def get_answer():
    answered = _answer_event.wait(timeout=POLL_TIMEOUT)
    with _lock:
        ans = _pending_answer if answered else None
    return jsonify({"answer": ans})


@app.route("/answer", methods=["POST"])
def receive_answer():
    global _pending_answer, _pending_question
    data = request.get_json(force=True)
    with _lock:
        _pending_answer   = data.get("answer", "").strip()
        _pending_question = None
        _question_event.clear()
        _answer_event.set()
    return jsonify({"status": "ok"})


# ── Bot control endpoints ─────────────────────────────────────────────────────

@app.route("/pause", methods=["POST"])
def pause_bot():
    global _paused
    with _lock:
        _paused = True
        _resume_event.clear()
    push_log("⏸ Bot paused by user.", "WARN")
    print("[ChatServer] Bot PAUSED by user.")
    return jsonify({"status": "paused"})


@app.route("/resume", methods=["POST"])
def resume_bot():
    global _paused, _stopped
    with _lock:
        _paused  = False
        _stopped = False
        _resume_event.set()
    push_log("▶ Bot resumed by user.", "OK")
    print("[ChatServer] Bot RESUMED by user.")
    return jsonify({"status": "running"})


@app.route("/stop", methods=["POST"])
def stop_bot():
    global _paused, _stopped
    with _lock:
        _stopped = True
        _paused  = False          # unblock any pause-wait so the stop check is reached
        _resume_event.set()       # unblock wait_if_paused so bot reaches stop check
    push_log("⏹ Bot stopped by user.", "FAIL")
    print("[ChatServer] Bot STOPPED by user.")
    return jsonify({"status": "stopped"})


@app.route("/restart", methods=["POST"])
def restart_bot():
    global _paused, _stopped
    with _lock:
        _stopped = False
        _paused  = False
        _resume_event.set()
    push_log("🔄 Bot restarted by user.", "OK")
    print("[ChatServer] Bot RESTARTED by user.")
    return jsonify({"status": "running"})


@app.route("/status", methods=["GET"])
def get_status():
    with _lock:
        p = _paused
        s = _stopped
        q = _pending_question
    return jsonify({"paused": p, "stopped": s, "pending_question": q is not None})


@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "alive"})


# ── Bot helper functions (called from bot thread) ─────────────────────────────

def wait_if_paused():
    """Block the calling (bot) thread while paused. Returns immediately when running."""
    _resume_event.wait()


def is_stopped() -> bool:
    """Returns True if the user clicked Stop. Bot should exit its loop."""
    with _lock:
        return _stopped


# ── Server lifecycle ──────────────────────────────────────────────────────────

_server_thread: threading.Thread | None = None


def start_server():
    """Start the Flask server in a background daemon thread."""
    global _server_thread
    if _server_thread and _server_thread.is_alive():
        return
    _server_thread = threading.Thread(
        target=lambda: app.run(
            host="127.0.0.1", port=SERVER_PORT,
            debug=False, use_reloader=False
        ),
        daemon=True,
        name="ChatServer"
    )
    _server_thread.start()
    time.sleep(0.8)
    push_log(f"✅ Chat server started on http://127.0.0.1:{SERVER_PORT}", "OK")
    print(f"[ChatServer] Listening on http://127.0.0.1:{SERVER_PORT}")
