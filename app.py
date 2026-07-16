"""Flask web application for the AI Major Recommendation tool.

Serves a single-page experience where a student fills in a profile form and
then refines their major recommendations through a short chat-style Q&A.

Endpoints:
    GET  /            - render the app shell.
    POST /api/start   - begin a session from the profile form.
    POST /api/chat    - refine the recommendation with the student's answer.
"""

import os
import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, session

from src.recommender import MAX_QUESTIONS, refine_session, start_session
from src.utils import RecommenderError

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

# Server-side conversation store: session id -> {messages, questions_asked}.
# An in-memory dict is sufficient for a single-process app and keeps the large
# OpenAI message history out of the (4 KB) signed session cookie.
_SESSIONS: dict[str, dict] = {}


@app.route("/")
def index():
    """Render the single-page app."""
    return render_template("index.html", max_questions=MAX_QUESTIONS)


@app.post("/api/start")
def api_start():
    """Start a new recommendation session from the submitted profile form."""
    form = request.get_json(silent=True) or {}
    try:
        result, messages = start_session(form)
    except RecommenderError as exc:
        return jsonify({"error": str(exc)}), 502

    sid = uuid.uuid4().hex
    _SESSIONS[sid] = {"messages": messages, "questions_asked": 1}
    session["sid"] = sid

    result["questions_asked"] = 1
    result["max_questions"] = MAX_QUESTIONS
    result["done"] = not result["question"]
    return jsonify(result)


@app.post("/api/chat")
def api_chat():
    """Refine the recommendation using the student's latest answer."""
    sid = session.get("sid")
    state = _SESSIONS.get(sid) if sid else None
    if not state:
        return jsonify({"error": "Your session expired. Please start again."}), 400

    payload = request.get_json(silent=True) or {}
    answer = (payload.get("answer") or "").strip()
    if not answer:
        return jsonify({"error": "Please type an answer first."}), 400

    try:
        result, messages = refine_session(
            state["messages"], answer, state["questions_asked"]
        )
    except RecommenderError as exc:
        return jsonify({"error": str(exc)}), 502

    state["messages"] = messages
    state["questions_asked"] += 1

    result["questions_asked"] = state["questions_asked"]
    result["max_questions"] = MAX_QUESTIONS
    result["done"] = (not result["question"]) or state["questions_asked"] >= MAX_QUESTIONS

    if result["done"]:
        # Free the stored conversation once the session is complete.
        _SESSIONS.pop(sid, None)
        session.pop("sid", None)

    return jsonify(result)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
