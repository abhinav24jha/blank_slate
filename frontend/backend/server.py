# server.py
import os
import glob
import json
import time
import shlex
import requests
import subprocess
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS

COHERE_API_KEY = os.environ.get("COHERE_API_KEY")
COHERE_MODEL   = os.environ.get("COHERE_MODEL", "command-r-plus-08-2024")

# Folder that contains analytics_data.json and report outputs
DATA_DIR = os.environ.get("DATA_DIR", "./data")
ENV_REPORT_PATH = os.environ.get("REPORT_PATH")  # optional absolute override

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

@app.get("/api/health")
def health():
    return {"ok": True, "cohereKey": bool(COHERE_API_KEY)}

# ---------- Report (legacy fallback) ----------
# Renamed to avoid clashing with the main /api/report route below.
@app.get("/api/report_legacy")
def get_report_legacy():
    """Get the markdown report (legacy finder, kept for backward compat)."""
    try:
        prefix = request.args.get("prefix") or None

        possible_dirs = [
            "./data",
            "data",
            "./data/outputs",
            "../data",
            "../data/outputs",
            "data/outputs",
        ]

        report_content = None
        for data_dir in possible_dirs:
            if os.path.exists(data_dir):
                if prefix:
                    report_files = glob.glob(os.path.join(data_dir, f"{prefix}*.report.md"))
                else:
                    report_files = glob.glob(os.path.join(data_dir, "*.report.md"))

                if report_files:
                    latest_report = max(report_files, key=os.path.getmtime)
                    with open(latest_report, "r", encoding="utf-8") as f:
                        report_content = f.read()
                    break

        if report_content:
            return {"exists": True, "markdown": report_content}
        else:
            return {"exists": False, "markdown": ""}, 404

    except Exception as e:
        return {"exists": False, "markdown": "", "error": str(e)}, 500

# ---------- Cohere chat ----------
@app.post("/api/cohere/chat")
def cohere_chat():
    if not COHERE_API_KEY:
        return jsonify({"error": "COHERE_API_KEY not set on server"}), 500

    body = request.get_json(force=True) or {}
    messages = body.get("messages", [])
    model = body.get("model", COHERE_MODEL)

    convo_lines = []
    for m in messages:
        role = m.get("role", "user")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        prefix = "User:" if role == "user" else "Assistant:"
        convo_lines.append(f"{prefix} {content}")
    joined = "\n".join(convo_lines) or "Hello!"

    try:
        r = requests.post(
            "https://api.cohere.ai/v1/chat",
            headers={
                "Authorization": f"Bearer {COHERE_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": model, "message": joined, "temperature": 0.3},
            timeout=45,
        )
        r.raise_for_status()
        data = r.json()
        return jsonify({"text": data.get("text", "")})
    except requests.RequestException as e:
        return jsonify({"error": f"Cohere request failed: {e}"}), 502

# ---------- Report lookup helpers ----------
def _find_report_path(prefix: str | None):
    """
    If REPORT_PATH is set and exists, use it.
    Otherwise, look under DATA_DIR for:
      - f"{prefix}*.report.md" when prefix is provided
      - "*.report.md" as a fallback
    Returns the first match or raises FileNotFoundError.
    """
    if ENV_REPORT_PATH and os.path.exists(ENV_REPORT_PATH):
        return ENV_REPORT_PATH

    patterns = []
    if prefix:
        patterns.append(os.path.join(DATA_DIR, f"{prefix}*.report.md"))
    patterns.append(os.path.join(DATA_DIR, "*.report.md"))

    for pat in patterns:
        matches = sorted(glob.glob(pat))
        if matches:
            return matches[0]

    raise FileNotFoundError(f"No report matching {patterns} in {DATA_DIR}")

def load_report(prefix: str | None):
    try:
        path = _find_report_path(prefix)
    except FileNotFoundError:
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

# This is the primary report route your frontend should use.
@app.get("/api/report")
def api_report():
    prefix = request.args.get("prefix") or None
    md = load_report(prefix)
    if md is None:
        return jsonify({"exists": False, "markdown": ""}), 404
    return jsonify({"exists": True, "markdown": md})

@app.get("/api/research/status")
def research_status():
    """Check if research data exists and return a quick summary."""
    prefix = request.args.get("prefix") or None

    try:
        if prefix:
            report_files = glob.glob(os.path.join(DATA_DIR, f"{prefix}*.report.md"))
        else:
            report_files = glob.glob(os.path.join(DATA_DIR, "*.report.md"))

        if report_files:
            latest_report = max(report_files, key=os.path.getmtime)
            with open(latest_report, "r", encoding="utf-8") as f:
                report_content = f.read()

            lines = report_content.split("\n")
            bullets = []
            for line in lines:
                s = line.strip()
                if s.startswith("-") or s.startswith("*"):
                    bullets.append(s[1:].strip())
                if len(bullets) >= 5:
                    break

            return jsonify({
                "status": "complete",
                "data": {
                    "type": "markdown_report",
                    "content": report_content,
                    "items": len(bullets),
                    "sites": 4,
                    "bullets": bullets[:5],
                    "sites_list": ["waterloo.ca", "ontario.ca", "grandriver.ca", "regionofwaterloo.ca"],
                }
            })
        else:
            return jsonify({"status": "no_data"})

    except Exception as e:
        return jsonify({"status": "error", "error": str(e)})

@app.get("/api/analytics/data")
def get_analytics_data():
    """Serve analytics data from DATA_DIR/analytics_data.json, or a simple fallback."""
    try:
        json_file_path = os.path.join(DATA_DIR, "analytics_data.json")
        if os.path.exists(json_file_path):
            with open(json_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return jsonify(data)
        else:
            # Fallback: minimal generated data if the file is missing
            time_points = list(range(0, 25, 1))
            env1_data = [{"x": i, "y": 30 + i * 0.3} for i in time_points]
            env2_data = [{"x": i, "y": 50 + i * 1.2} for i in time_points]
            env3_data = [{"x": i, "y": 70 + i * 1.0} for i in time_points]
            env4_data = [{"x": i, "y": 45 + i * 0.9} for i in time_points]

            cost_env1 = [{"x": i, "y": 15 + i * 1.5} for i in time_points]
            cost_env2 = [{"x": i, "y": 25 + i * 1.3} for i in time_points]
            cost_env3 = [{"x": i, "y": 8 + i * 1.2} for i in time_points]
            cost_env4 = [{"x": i, "y": 18 + i * 1.4} for i in time_points]

            time_env1 = [{"x": i, "y": 2 + i * 0.3} for i in time_points]
            time_env2 = [{"x": i, "y": 6 + i * 0.6} for i in time_points]
            time_env3 = [{"x": i, "y": 12 + i * 1.5} for i in time_points]
            time_env4 = [{"x": i, "y": 8 + i * 1.2} for i in time_points]

            return jsonify({
                "metrics": {
                    "efficiency": {
                        "env1": env1_data,
                        "env2": env2_data,
                        "env3": env3_data,
                        "env4": env4_data,
                        "label": "Efficiency %",
                        "color_env1": "#ef4444",
                        "color_env2": "#3b82f6",
                        "color_env3": "#10b981",
                        "color_env4": "#8b5cf6"
                    },
                    "cost": {
                        "env1": cost_env1,
                        "env2": cost_env2,
                        "env3": cost_env3,
                        "env4": cost_env4,
                        "label": "Cost Reduction %",
                        "color_env1": "#ef4444",
                        "color_env2": "#3b82f6",
                        "color_env3": "#10b981",
                        "color_env4": "#8b5cf6"
                    },
                    "time_saved": {
                        "env1": time_env1,
                        "env2": time_env2,
                        "env3": time_env3,
                        "env4": time_env4,
                        "label": "Time Saved (hours/month)",
                        "color_env1": "#ef4444",
                        "color_env2": "#3b82f6",
                        "color_env3": "#10b981",
                        "color_env4": "#8b5cf6"
                    }
                },
                "summary": {
                    "efficiency_improvement": "42%",
                    "cost_reduction": "68%",
                    "time_saved": "38 hours/month",
                    "overall_rating": "Excellent"
                }
            })

    except Exception as e:
        return jsonify({"error": f"Failed to load analytics data: {str(e)}"}), 500

@app.post("/api/research/start")
def start_research():
    """Start the deep research pipeline with user input (in a background thread)."""
    try:
        body = request.get_json(force=True) or {}
        space = body.get("space", "")
        user_input = body.get("userInput", "")
        run_pipeline = body.get("runPipeline", False)

        if not space or not user_input:
            return jsonify({"error": "Space and userInput are required"}), 400

        prefix = f"{space.lower().replace(' ', '_')}_{int(time.time())}"

        if run_pipeline:
            def run_pipeline_thread():
                try:
                    topic = f"{space} optimization and development"
                    escaped_user_input = shlex.quote(user_input)
                    escaped_topic = shlex.quote(topic)
                    escaped_prefix = shlex.quote(prefix)

                    print(f"Starting research pipeline for: {space}")
                    print(f"Topic: {topic}")
                    print(f"User input: {user_input[:100]}...")

                    result = subprocess.run(
                        [
                            "python", "deep_research_pipeline.py",
                            escaped_user_input,
                            escaped_topic,
                            escaped_prefix,
                            "gemini",
                        ],
                        capture_output=True,
                        text=True,
                        cwd=".",
                    )

                    if result.returncode == 0:
                        print(f"Research completed successfully for {space}")
                        print(f"Output: {result.stdout}")
                    else:
                        print(f"Research failed for {space}: {result.stderr}")
                        print(f"Return code: {result.returncode}")

                except Exception as e:
                    print(f"Error running research pipeline: {e}")

            thread = threading.Thread(target=run_pipeline_thread, daemon=True)
            thread.start()

            return jsonify({
                "success": True,
                "message": "Research pipeline started",
                "prefix": prefix
            })
        else:
            return jsonify({
                "success": True,
                "message": "Using existing research data",
                "prefix": prefix
            })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Example:
    #   export COHERE_API_KEY=...
    #   export DATA_DIR=./data
    #   python server.py
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5002)), debug=True)
