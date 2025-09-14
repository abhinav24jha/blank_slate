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
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from .agent_schemas import AgentSnapshot as SnapModel, Decision as DecisionModel, NextIntent as NextIntentModel
from .agent_schemas import AgentPersona, AgentState, MemoryEvent
from .agent_state import init_agent, get_state, append_memory, persist_persona
from .agent_brain import llm_decide_intent, llm_chat
from .llm_clients.ollama_client import warmup_model


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

app = FastAPI(title="Agent Brain Server", version="0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Warmup model on server startup for immediate demo readiness."""
    logging.info("Server starting - warming up model for demo...")
    # Run warmup in background to not block server startup
    import threading
    def background_warmup():
        warmup_model("qwen2.5:3b-instruct", timeout=120)
        logging.info("Background model warmup completed")
    
    thread = threading.Thread(target=background_warmup, daemon=True)
    thread.start()

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
    agents: List[SnapModel]
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
@app.post("/warmup")
def warmup_endpoint():
    """Warmup the model for faster first requests."""
    model = "qwen2.5:3b-instruct"
    logging.info(f"Warming up model: {model}")
    success = warmup_model(model, timeout=60)
    if success:
        logging.info("Model warmup completed successfully")
        return {"status": "warmed", "model": model}
    else:
        logging.warning("Model warmup failed")
        return {"status": "failed", "model": model}


@app.post("/start_run", response_model=StartRunResp)
def start_run(req: StartRunReq = Body(...)):
    # Auto-warmup on first run to ensure smooth demo experience
    if not hasattr(start_run, '_warmed'):
        logging.info("First run detected - warming up model...")
        warmup_model("qwen2.5:3b-instruct", timeout=60)
        start_run._warmed = True
    
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


class RegisterAgent(BaseModel):
    id: str
    role: str
    seed: Optional[int] = None
    prefs: Optional[Dict[str, str]] = None


class RegisterReq(BaseModel):
    runId: str
    agents: List[RegisterAgent]


@app.post("/register_agents", response_model=OkResp)
def register_agents(req: RegisterReq = Body(...)):
    os.makedirs(os.path.join(ROOT_OUT, "brain_runs", req.runId, "agents"), exist_ok=True)
    for a in req.agents:
        st = init_agent(req.runId, a.id, a.role, a.seed, a.prefs)
        persist_persona(req.runId, a.id, st.persona)
    return OkResp(ok=True)


@app.post("/decide", response_model=DecideResp)
def decide(req: DecideReq = Body(...)):
    run = RUNS.get(req.runId)
    if not run:
        logging.warning(f"No run found for runId={req.runId}, processing anyway")
        # Process anyway for debugging

    out: List[Decision] = []
    context = req.context or {}
    meeting = context.get("meeting", False)

    model = "qwen2.5:3b-instruct"  # default local model name for Ollama; can be changed
    # Sequential small-batch processing (client already batches + throttles). Keeps server simple and robust.
    for ag in req.agents:
        # Ensure state
        st = get_state(req.runId, ag.id) or init_agent(req.runId, ag.id, ag.role)
        try:
            category, thought, mem = llm_decide_intent(model, st, ag.model_dump(), context)
            logging.info(f"LLM SUCCESS for {ag.id}: thought='{thought}', category={category}")
        except Exception as e:
            logging.warning(f"LLM FAILED for {ag.id}: {e}")
            best_need, best_val = None, -1.0
            for k, v in (ag.needs or {}).items():
                if v is None: continue
                if v > best_val: best_need, best_val = k, v
            category = NEED_TO_CATEGORY.get(best_need or "leisure", "retail")
            thought = f"Heading to {category}."
            mem = f"Chose {category} after considering needs."
        append_memory(req.runId, ag.id, MemoryEvent(ts=_now_iso(), kind="decision", text=mem, tags=[category]))
        out.append(Decision(id=ag.id, next_intent=NextIntent(category=category), thought=thought, chat=None))
        # Small delay to prevent overwhelming Ollama with concurrent requests
        time.sleep(0.1)

    # Append decisions to file
    files = _ensure_run_dirs(req.runId)
    with open(files["decisions"], "a", encoding="utf-8") as f:
        for d in out:
            f.write(json.dumps(d.model_dump(), ensure_ascii=False) + "\n")

    if run: RUNS[req.runId]["decisions"] += len(out)
    logging.info(f"Decide processed {len(req.agents)} agents -> {len(out)} decisions")
    return DecideResp(decisions=out)


class ChatPair(BaseModel):
    aId: str
    bId: str


class ChatReq(BaseModel):
    runId: str
    pairs: List[ChatPair]
    context: Optional[Dict[str, Any]] = None


class ChatResp(BaseModel):
    pairs: List[Dict[str, str]]


@app.post("/chat", response_model=ChatResp)
def chat(req: ChatReq = Body(...)):
    out = []
    model = "qwen2.5:3b-instruct"
    for p in req.pairs:
        a = get_state(req.runId, p.aId)
        b = get_state(req.runId, p.bId)
        if not a or not b:
            continue
        res = llm_chat(model, a, b, req.context or {})
        out.append({"aId": p.aId, "bId": p.bId, "a_line": res["a_line"], "b_line": res["b_line"]})
        append_memory(req.runId, p.aId, MemoryEvent(ts=_now_iso(), kind="chat", text=res["mem_a"], tags=["chat", p.bId]))
        append_memory(req.runId, p.bId, MemoryEvent(ts=_now_iso(), kind="chat", text=res["mem_b"], tags=["chat", p.aId]))
    return ChatResp(pairs=out)


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