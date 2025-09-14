#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minimal brain server for hero agents (fast to integrate for the demo).

Endpoints:
- POST /start_run  {hypothesisId, seed, speed} -> {runId}
- POST /decide     {runId, agents:[{id,pos,needs,role}], context?} -> {decisions:[...]}
- POST /metrics    {runId, samples:[...]} -> {ok:true}
- POST /end_run    {runId} -> {saved:{paths}}

Design:
- Stateless-ish; keeps small in-memory state for runs; writes metrics to disk.
- LLM optional: uses GOOGLE_API_KEY if present to craft a short thought; otherwise deterministic template.
- Decision policy: pick next intent from highest need, with meeting bias toward cafe/restaurant (social/caffeine/hunger).
"""

from __future__ import annotations
import os, json, time, uuid, random, logging
from typing import Dict, List, Any, Optional

from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

app = FastAPI(title="Agent Brain Server", version="0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ROOT_OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), "out"))
RUNS: Dict[str, Dict[str, Any]] = {}


# ---------------- Models ----------------
class StartRunReq(BaseModel):
    hypothesisId: str = Field(default="base")
    seed: int = Field(default=42)
    speed: float = Field(default=1.0)

class StartRunResp(BaseModel):
    runId: str

class AgentSnapshot(BaseModel):
    id: str
    role: str
    pos: List[float]  # [x, y] in grid coords
    needs: Dict[str, float]
    time_of_day: Optional[str] = None

class DecideReq(BaseModel):
    runId: str
    agents: List[AgentSnapshot]
    context: Optional[Dict[str, Any]] = None

class NextIntent(BaseModel):
    category: str
    name: Optional[str] = None

class Decision(BaseModel):
    id: str
    next_intent: NextIntent
    thought: Optional[str] = None
    chat: Optional[str] = None

class DecideResp(BaseModel):
    decisions: List[Decision]

class MetricsReq(BaseModel):
    runId: str
    samples: List[Dict[str, Any]]

class OkResp(BaseModel):
    ok: bool = True

class EndRunReq(BaseModel):
    runId: str

class EndRunResp(BaseModel):
    saved: Dict[str, str]


# ---------------- Utils ----------------
NEED_TO_CATEGORY = {
    "hunger": "restaurant",
    "caffeine": "cafe",
    "groceries": "grocery",
    "health": "pharmacy",
    "education": "education",
    "leisure": "retail",
    "social": "cafe",
}

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def _ensure_run_dirs(run_id: str) -> Dict[str, str]:
    run_dir = os.path.join(ROOT_OUT, "brain_runs", run_id)
    os.makedirs(run_dir, exist_ok=True)
    files = {
        "metrics": os.path.join(run_dir, "metrics.jsonl"),
        "decisions": os.path.join(run_dir, "decisions.jsonl"),
        "summary": os.path.join(run_dir, "summary.json"),
    }
    return files


# ---------------- Endpoints ----------------
@app.post("/start_run", response_model=StartRunResp)
def start_run(req: StartRunReq = Body(...)):
    run_id = str(uuid.uuid4())
    random.seed(req.seed)
    RUNS[run_id] = {
        "hypothesisId": req.hypothesisId,
        "seed": req.seed,
        "speed": req.speed,
        "started_at": _now_iso(),
        "samples": 0,
        "decisions": 0,
    }
    _ensure_run_dirs(run_id)
    logging.info("[run] start id=%s hyp=%s seed=%s", run_id, req.hypothesisId, req.seed)
    return StartRunResp(runId=run_id)


@app.post("/decide", response_model=DecideResp)
def decide(req: DecideReq = Body(...)):
    run = RUNS.get(req.runId)
    if not run:
        return DecideResp(decisions=[])

    out: List[Decision] = []
    context = req.context or {}
    meeting = context.get("meeting", False)

    for ag in req.agents:
        # Choose need → category
        best_need = None
        best_val = -1.0
        for k, v in (ag.needs or {}).items():
            if v is None: continue
            if v > best_val:
                best_need, best_val = k, v

        category = NEED_TO_CATEGORY.get(best_need or "leisure", "retail")

        # Meeting nudges toward cafe/restaurant
        if meeting and category not in ("cafe", "restaurant"):
            category = random.choice(["cafe", "restaurant"])  # small social bias

        # Short thought template (LLM optional)
        role = ag.role or "person"
        tod = ag.time_of_day or ""
        if best_need:
            thought = f"As a {role}, I'm feeling {best_need} {('this ' + tod) if tod else ''}. I'll head to a {category}."
        else:
            thought = f"As a {role}, I'll explore a nearby {category}."

        out.append(Decision(id=ag.id, next_intent=NextIntent(category=category), thought=thought))

    # Append decisions to file
    files = _ensure_run_dirs(req.runId)
    with open(files["decisions"], "a", encoding="utf-8") as f:
        for d in out:
            f.write(json.dumps(d.model_dump(), ensure_ascii=False) + "\n")

    RUNS[req.runId]["decisions"] += len(out)
    return DecideResp(decisions=out)


@app.post("/metrics", response_model=OkResp)
def metrics(req: MetricsReq = Body(...)):
    run = RUNS.get(req.runId)
    if not run:
        return OkResp(ok=False)
    files = _ensure_run_dirs(req.runId)
    with open(files["metrics"], "a", encoding="utf-8") as f:
        for s in req.samples or []:
            s["ts"] = _now_iso()
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    RUNS[req.runId]["samples"] += len(req.samples or [])
    return OkResp(ok=True)


@app.post("/end_run", response_model=EndRunResp)
def end_run(req: EndRunReq = Body(...)):
    run = RUNS.pop(req.runId, None)
    files = _ensure_run_dirs(req.runId)
    summary = {
        "runId": req.runId,
        "hypothesisId": (run or {}).get("hypothesisId"),
        "seed": (run or {}).get("seed"),
        "decisions": (run or {}).get("decisions", 0),
        "samples": (run or {}).get("samples", 0),
        "ended_at": _now_iso(),
    }
    with open(files["summary"], "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    logging.info("[run] end id=%s -> %s", req.runId, files["summary"])
    return EndRunResp(saved=files)


if __name__ == "__main__":
    # Run with:  uvicorn simulation.brain_server:app --host 127.0.0.1 --port 9000 --reload
    import uvicorn
    uvicorn.run("simulation.brain_server:app", host="127.0.0.1", port=9000, reload=True)


