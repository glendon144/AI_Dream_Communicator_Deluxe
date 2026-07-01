from __future__ import annotations

import os
from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv

from webmcp_client import WebMCPClient, WebMCPClientError


load_dotenv()

app = Flask(__name__)
client = WebMCPClient.from_env()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def api_status():
    try:
        return jsonify({"ok": True, "status": client.status()})
    except WebMCPClientError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.get("/api/actions")
def api_actions():
    try:
        return jsonify({"ok": True, "actions": client.list_actions()})
    except WebMCPClientError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.get("/api/action/<name>")
def api_action(name: str):
    try:
        action = client.get_action(name)
        if not action:
            return jsonify({"ok": False, "error": f"Unknown action: {name}"}), 404
        return jsonify({"ok": True, "action": action})
    except WebMCPClientError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/call")
def api_call():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    parameters = data.get("parameters") or {}

    if not name:
        return jsonify({"ok": False, "error": "Missing action name."}), 400
    if not isinstance(parameters, dict):
        return jsonify({"ok": False, "error": "parameters must be an object."}), 400

    try:
        result = client.call_action(name, parameters)
        status = 200 if result.get("ok", True) else 400
        return jsonify(result), status
    except WebMCPClientError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5054"))
    debug = os.getenv("FLASK_DEBUG", "1") == "1"
    app.run(host=host, port=port, debug=debug)
