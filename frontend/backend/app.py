import os
import glob
import json
import time
import hashlib
import re
import subprocess
import threading
import sys
from functools import lru_cache
from urllib.parse import urlparse

from flask import Flask, jsonify, request, Response, stream_with_context
from flask_cors import CORS

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------
# Try multiple possible data directory locations
possible_dirs = [
    "./data/outputs",
    "./data",
    "../data/outputs",
    "../data",
    "data/outputs",
    "data",
    "/Users/additimehta/Documents/fun_code/htn/htn-ui/backend/data/outputs",
    "/Users/additimehta/Documents/fun_code/htn/htn-ui/backend/data",
]

DATA_DIR = None
for dir_path in possible_dirs:
    if os.path.exists(dir_path):
        DATA_DIR = dir_path
        break

if DATA_DIR is None:
    DATA_DIR = os.environ.get("DATA_DIR", "./data")

print(f"🔍 DATA_DIR set to: {DATA_DIR}")
print(f"🔍 Current working directory: {os.getcwd()}")
print(f"🔍 Full data path: {os.path.abspath(DATA_DIR)}")
print(f"🔍 Data directory exists: {os.path.exists(DATA_DIR)}")
if os.path.exists(DATA_DIR):
    print(f"🔍 Files in data directory: {os.listdir(DATA_DIR)}")
else:
    print(f"❌ Data directory does not exist, will create it")
ENV_EVIDENCE_PATH = os.environ.get("EVIDENCE_PATH")
ENV_ROUNDS_PATH = os.environ.get("ROUNDS_PATH")

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------
# File discovery & caching helpers
# ---------------------------------------------------------------------
def _find_file_by_suffix(suffix: str, prefix: str | None = None) -> str:
    """
    Return the first file that matches "<prefix>*<suffix>" in DATA_DIR.
    Env overrides (EVIDENCE_PATH/ROUNDS_PATH) are honored when suffix matches.
    """
    override = None
    if suffix == ".evidence.json":
        override = ENV_EVIDENCE_PATH
    elif suffix == ".rounds.json":
        override = ENV_ROUNDS_PATH

    if override and os.path.exists(override):
        print(f"🔍 Using override path: {override}")
        return override

    pattern = f"{prefix}*{suffix}" if prefix else f"*{suffix}"
    search_path = os.path.join(DATA_DIR, pattern)
    print(f"🔍 Searching for pattern: {pattern} in {DATA_DIR}")
    print(f"🔍 Full search path: {search_path}")
    matches = sorted(glob.glob(search_path))
    print(f"🔍 Found matches: {matches}")

    # Also show all files in the directory for debugging
    all_files = os.listdir(DATA_DIR) if os.path.exists(DATA_DIR) else []
    print(f"🔍 All files in directory: {all_files}")

    if not matches:
        raise FileNotFoundError(f"No file matching '{pattern}' in {DATA_DIR}")
    print(f"🔍 Returning file: {matches[0]}")
    return matches[0]


def _file_info(suffix: str, prefix: str | None = None) -> tuple[str, float]:
    """
    Returns (path, mtime) so that downstream cache keys change when file updates.
    """
    path = _find_file_by_suffix(suffix, prefix)
    return path, os.path.getmtime(path)


# NEW: try multiple acceptable suffixes (e.g., test_*.json OR *.json)
def _file_info_any(suffixes: list[str], prefix: str | None = None) -> tuple[str, float]:
    last_err = None
    for s in suffixes:
        try:
            return _file_info(s, prefix)
        except FileNotFoundError as e:
            last_err = e
    raise last_err or FileNotFoundError("No matching file found")


@lru_cache(maxsize=64)
def _read_json(path: str, mtime: float):
    """
    Read JSON with (path, mtime) as cache key. Retries briefly to tolerate
    concurrent writes from producer scripts.
    """
    for _ in range(5):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            time.sleep(0.12)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# ---------------------------------------------------------------------
# Loaders (mtime-aware; no external caching here)
# ---------------------------------------------------------------------
def load_evidence(prefix: str | None):
    """
    Loads evidence from file ending with .evidence.json OR evidence.json.
    Accepts either:
      - list[ { id, url, title, snippet? ... } ]
      - { items: [ ... ], status?: "done" }
    Returns { "items": [...], "by_id": { id: item }, "status": <opt> }
    """
    print(f"🔍 load_evidence called with prefix: {prefix}")
    # accept either naming scheme
    path, mtime = _file_info_any([".evidence.json", "evidence.json"], prefix)
    print(f"📁 Loading evidence from: {path}")
    raw = _read_json(path, mtime)
    print(
        f"📄 Loaded evidence data: {type(raw)}, length: {len(raw) if isinstance(raw, (list, dict)) else 'unknown'}"
    )

    if isinstance(raw, dict):
        items = raw.get("items", [])
        status = raw.get("status")
    else:
        items = raw
        status = None

    if not isinstance(items, list):
        items = []

    by_id = {}
    for it in items:
        _id = str(
            it.get("id")
            or it.get("evidence_id")
            or it.get("url")
            or f"e{len(by_id)}"
        )
        by_id[_id] = it

    return {"items": items, "by_id": by_id, "status": status}


def load_rounds(prefix: str | None):
    """
    Loads rounds from any file ending with .rounds.json OR rounds.json.
    Allows either:
      - dict with "sites": [host,...] and/or "status": "done"
      - list of rounds (each may contain "sites" or "queries")
    """
    try:
        path, mtime = _file_info_any([".rounds.json", "rounds.json"], prefix)
        print(f"Loading rounds from: {path}")
    except FileNotFoundError:
        print(f"No rounds file found for prefix: {prefix}")
        return {}
    return _read_json(path, mtime)

# ---------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------
def url_host(u: str) -> str:
    try:
        p = urlparse(u)
        return (p.netloc or u).lower()
    except Exception:
        return u


def dedupe_preserve(xs):
    seen, out = set(), []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def compute_sites(rounds, evidence_items, limit: int = 15) -> list[str]:
    """
    Preferred: extract from rounds queries like 'site:domain.com'.
    Fallback: derive from evidence URLs.
    """
    sites: list[str] = []
    # If rounds is dict with explicit sites
    if isinstance(rounds, dict) and isinstance(rounds.get("sites"), list):
        sites = list(dict.fromkeys(rounds["sites"]))  # dedupe preserve order
    # Or list of rounds possibly containing queries
    elif isinstance(rounds, list):
        for r in rounds:
            if isinstance(r, dict):
                if isinstance(r.get("sites"), list):
                    for s in r["sites"]:
                        if s not in sites:
                            sites.append(s)
                if isinstance(r.get("queries"), list):
                    for q in r["queries"]:
                        for site in re.findall(r"site:([a-zA-Z0-9.-]+)", q):
                            if site not in sites:
                                sites.append(site)

    if not sites:
        for it in evidence_items[:20]:
            host = url_host(it.get("url", ""))
            if host and host not in sites:
                sites.append(host)

    return sites[:limit]


def compute_bullets(evidence_items, limit: int = 4) -> list[str]:
    bullets: list[str] = []
    for it in evidence_items[:limit]:
        title = (it.get("title") or it.get("headline") or "").strip()
        snippet = (it.get("snippet") or it.get("summary") or "").strip()
        if title:
            bullets.append(title)
        elif snippet:
            bullets.append(snippet[:140] + ("…" if len(snippet) > 140 else ""))
    return bullets


def compute_cursor(evidence_items, sites) -> str:
    """
    Stable hash of the content we surface to the client. Changes when files change.
    """
    h = hashlib.sha1()
    try:
        h.update(json.dumps(evidence_items, sort_keys=True, ensure_ascii=False).encode())
    except Exception:
        h.update(str(evidence_items).encode())
    h.update(json.dumps(sites, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()


def is_done(prefix: str | None) -> bool:
    """
    Determine 'done' without relying on a running process:
    1) a file ending with .report.json OR report.json exists, OR
    2) rounds has {"status": "done"}, OR
    3) evidence has {"status": "done"}.
    """
    # 1) report presence (any naming scheme)
    try:
        _find_file_by_suffix(".report.json", prefix)
        return True
    except FileNotFoundError:
        pass
    try:
        _find_file_by_suffix("report.json", prefix)
        return True
    except FileNotFoundError:
        pass

    # 2) rounds status
    try:
        r = load_rounds(prefix)
        if isinstance(r, dict) and str(r.get("status", "")).lower() == "done":
            return True
    except Exception:
        pass

    # 3) evidence status (now preserved by load_evidence)
    try:
        e = load_evidence(prefix)
        if isinstance(e, dict) and str(e.get("status", "")).lower() == "done":
            return True
    except Exception:
        pass

    return False


def run_research_pipeline(prefix: str | None = None) -> bool:
    """
    Run the deep_research_pipeline.py script and return True if successful.
    """
    try:
        cmd = [sys.executable, "deep_research_pipeline.py"]
        if prefix:
            cmd.extend(["--prefix", prefix])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print("Pipeline stderr:\n", result.stderr)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"Research pipeline timed out for prefix: {prefix}")
        return False
    except Exception as e:
        print(f"Error running research pipeline: {e}")
        return False

# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------
@app.get("/api/health")
def health():
    print("🏥 Health check requested")
    return jsonify({"ok": True, "timestamp": time.time()})


@app.get("/api/research/status")
def research_status():
    """Check if research data exists and return it"""
    prefix = request.args.get("prefix") or None
    
    try:
        # First try to load JSON data with the specified prefix
        ev = load_evidence(prefix)
        rounds = load_rounds(prefix) or {}
        sites = compute_sites(rounds, ev["items"])
        bullets = compute_bullets(ev["items"])

        return jsonify(
            {
                "status": "complete",
                "data": {
                    "items": len(ev["items"]),
                    "sites": len(sites),
                    "bullets": bullets,
                    "sites_list": sites,
                },
            }
        )
    except FileNotFoundError:
        # If no JSON data, check for markdown report with prefix
        try:
            if prefix:
                # Look for prefix-specific report file
                report_file = _find_file_by_suffix("report.md", prefix)
            else:
                # Look for any report file
                report_file = _find_file_by_suffix("report.md")
                
            if report_file:
                with open(report_file, "r", encoding="utf-8") as f:
                    report_content = f.read()
                return jsonify(
                    {
                        "status": "complete",
                        "data": {
                            "type": "markdown_report",
                            "content": report_content,
                        },
                    }
                )
            else:
                return jsonify({"status": "no_data"})
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)})


@app.get("/api/test-stream")
def test_stream():
    """
    Simple test endpoint to verify SSE is working
    """
    print("🧪 Test stream requested")

    @stream_with_context
    def gen():
        yield sse({"type": "test", "message": "Hello from backend!"})
        time.sleep(1)
        yield sse({"type": "test", "message": "Second message"})
        time.sleep(1)
        yield sse({"type": "test", "message": "Final message"})

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return Response(gen(), headers=headers)


@app.get("/api/evidence")
def api_evidence():
    prefix = request.args.get("prefix") or None
    try:
        return jsonify(load_evidence(prefix))
    except FileNotFoundError as e:
        return jsonify({"items": [], "by_id": {}, "error": str(e)}), 404


@app.get("/api/rounds")
def api_rounds():
    prefix = request.args.get("prefix") or None
    try:
        return jsonify(load_rounds(prefix))
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404


@app.get("/api/research")
def api_research():
    """
    Combined non-stream endpoint (useful for reports or debugging).
    """
    objective = (request.args.get("objective") or "").strip() or "your objective"
    prefix = request.args.get("prefix") or None
    try:
        ev = load_evidence(prefix)
    except FileNotFoundError:
        ev = {"items": [], "by_id": {}}
    try:
        rounds = load_rounds(prefix)
    except FileNotFoundError:
        rounds = {}

    return jsonify(
        {
            "objective": objective,
            "rounds": rounds,
            "evidence": ev,
        }
    )


# ---------------------- FIXED: long-lived polling SSE ----------------------
@app.get("/api/research/stream")
def api_research_stream():
    """
    Long-lived SSE:
      - Starts the research pipeline (non-blocking) ONCE per request
      - Polls the filesystem for new/updated JSON
      - Emits events as things change (prompt/searched/round/progress/snapshot/done)
      - Sends heartbeats to keep connections alive
    """
    objective = (request.args.get("objective") or "").strip() or "your objective"
    prefix = request.args.get("prefix") or None

    print(f"🌐 SSE request received - objective: {objective}, prefix: {prefix}")
    os.makedirs(DATA_DIR, exist_ok=True)

    # Kick off background research (non-blocking)
    def run_research_background():
        try:
            cmd = [sys.executable, "clean_and_research.py", objective]
            if prefix:
                cmd.append(prefix)
            subprocess.Popen(
                cmd,
                cwd=os.path.dirname(os.path.abspath(__file__)),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )
            print("🚀 Background research started.")
        except Exception as e:
            print(f"❌ Background research error: {e}")

    threading.Thread(target=run_research_background, daemon=True).start()

    @stream_with_context
    def gen():
        # Initial UX events
        yield sse({"type": "prompt", "text": f"Search the web for {objective}"})
        yield sse({"type": "searched", "query": objective, "results": 0})
        yield sse(
            {
                "type": "thinking-summary",
                "title": f"Synthesizing sources for “{objective}”",
                "bullets": [
                    "Scanning sources and queuing queries",
                    "De-duplicating and clustering signals",
                    "Extracting key evidence",
                ],
            }
        )

        last_cursor = ""
        last_sites: list[str] = []
        last_rounds_seen = None
        last_ev_count = -1
        started = time.time()
        timeout_s = float(request.args.get("timeout", 300))  # 5 min
        heartbeat_every = 12  # seconds
        last_heartbeat = 0.0

        while True:
            now = time.time()
            # Heartbeat keeps connections alive through proxies
            if now - last_heartbeat > heartbeat_every:
                yield ": keep-alive\n\n"
                last_heartbeat = now

            # Attempt to read current state
            try:
                ev = load_evidence(prefix)
            except FileNotFoundError:
                ev = {"items": [], "by_id": {}}
            try:
                rounds = load_rounds(prefix) or {}
            except FileNotFoundError:
                rounds = {}

            sites = compute_sites(rounds, ev.get("items", []))
            bullets = compute_bullets(ev.get("items", []))
            cursor = compute_cursor(ev.get("items", []), sites)
            done = is_done(prefix)

            # Emit round/site chips if changed
            if rounds != last_rounds_seen or sites != last_sites:
                yield sse(
                    {
                        "type": "round",
                        "round_id": 1,
                        "queries": [],
                        "chips": sites,
                    }
                )
                last_rounds_seen = rounds
                last_sites = sites

            # Heuristic progress
            progress = 5
            if ev.get("items"):
                progress = max(progress, 10)
            if rounds:
                progress = max(progress, 50)
            if len(ev.get("items", [])) > max(0, last_ev_count):
                progress = max(progress, 90)
            if done:
                progress = 100

            if len(ev.get("items", [])) != last_ev_count:
                last_ev_count = len(ev.get("items", []))

            yield sse({"type": "progress", "value": progress, "status": "Working…"})

            # Opportunistic summary updates
            if bullets:
                yield sse(
                    {
                        "type": "thinking-summary",
                        "title": f"Findings for “{objective}”",
                        "bullets": bullets,
                    }
                )

            # Snapshot when content changes
            if cursor != last_cursor:
                last_cursor = cursor
                yield sse(
                    {
                        "type": "snapshot",
                        "cursor": cursor,
                        "results": len(ev.get("items", [])),
                        "sites": sites,
                    }
                )

            if done:
                yield sse({"type": "progress", "value": 100, "status": "Complete"})
                yield sse({"type": "done"})
                break

            if now - started > timeout_s:
                yield sse({"type": "progress", "value": progress, "status": "Timed out"})
                break

            time.sleep(0.5)  # poll interval

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return Response(gen(), headers=headers)
# ---------------------------------------------------------------------


@app.get("/api/research/poll")
def api_research_poll():
    """
    Long-poll for changes. Client passes last 'cursor'.
    Returns {changed: True, cursor, bullets, chips, results, done} when different
    or when 'done' is True; otherwise times out with {changed: False, cursor}.
    """
    objective = (request.args.get("objective") or "").strip() or "your objective"
    prefix = request.args.get("prefix") or None
    client_cursor = request.args.get("cursor") or ""
    timeout = float(request.args.get("timeout", 20))  # seconds
    interval = float(request.args.get("interval", 0.7))  # seconds

    started = time.time()
    while True:
        try:
            ev = load_evidence(prefix)
        except FileNotFoundError:
            ev = {"items": [], "by_id": {}}
        try:
            rounds = load_rounds(prefix) or {}
        except FileNotFoundError:
            rounds = {}

        sites = compute_sites(rounds, ev["items"])
        bullets = compute_bullets(ev["items"])
        cursor = compute_cursor(ev["items"], sites)
        done = is_done(prefix)

        if cursor != client_cursor or done:
            return jsonify(
                {
                    "objective": objective,
                    "changed": cursor != client_cursor,
                    "cursor": cursor,
                    "bullets": bullets,
                    "chips": sites,
                    "results": len(ev["items"]),
                    "done": done,
                }
            )

        if time.time() - started >= timeout:
            return jsonify(
                {
                    "objective": objective,
                    "changed": False,
                    "cursor": client_cursor,
                    "done": False,
                }
            )

        time.sleep(interval)

# ---------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------
if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    port = int(os.environ.get("PORT", 5001))
    print(f"🚀 Starting Flask server on http://0.0.0.0:{port}")
    print(f"📁 Data directory: {DATA_DIR}")
    print(f"📁 Data directory exists: {os.path.exists(DATA_DIR)}")
    if os.path.exists(DATA_DIR):
        print(f"📁 Files in data directory: {os.listdir(DATA_DIR)}")
    app.run(host="0.0.0.0", port=port, debug=True)
