#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Per-agent state and memory persistence.
"""

from __future__ import annotations
import os, json, time, random
from typing import Dict, Optional, List
from .agent_schemas import AgentState, AgentPersona, MemoryEvent


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "out", "brain_runs"))
_CACHE: Dict[str, Dict[str, AgentState]] = {}


def _run_dir(run_id: str) -> str:
    return os.path.join(ROOT, run_id)


def _agent_dir(run_id: str, agent_id: str) -> str:
    return os.path.join(_run_dir(run_id), "agents", agent_id)


def _mem_path(run_id: str, agent_id: str) -> str:
    return os.path.join(_agent_dir(run_id, agent_id), "mem.jsonl")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _ensure_cache(run_id: str):
    if run_id not in _CACHE:
        _CACHE[run_id] = {}


def create_persona(agent_id: str, role: str, seed: Optional[int] = None, prefs: Optional[Dict[str, str]] = None) -> AgentPersona:
    """Sample a slightly richer persona with consistent quirks/preferences per agent."""
    rnd = random.Random(seed or (hash(agent_id) & 0xffffffff))
    first = rnd.choice(["Alex","Sam","Taylor","Jordan","Riley","Casey","Jamie","Avery","Morgan","Drew"])  # neutral
    last = rnd.choice(["Lee","Patel","Nguyen","Kim","Singh","Brown","Garcia","Martin","Hernandez","Wilson"])

    core_traits = [
        "punctual","social","frugal","curious","optimistic","introvert","extrovert","planner","impulsive","health-conscious",
        "night-owl","early-riser","tech-savvy","bookish","foodie","gym-goer"
    ]
    traits = rnd.sample(core_traits, k=4)

    # Preferences influence needs/intents subtly
    base_prefs = {
        "coffee": rnd.choice(["low","med","high"]),
        "budget": rnd.choice(["low","med","high"]),
        "diet": rnd.choice(["omnivorous","vegetarian","vegan","halal","kosher","pescatarian"]),
        "mobility": rnd.choice(["walk","bus","bike"]),
        "study_spot": rnd.choice(["quiet","lively","outdoors"]) if role in ("student","education") else rnd.choice(["quiet","lively"]) ,
        "favorite": rnd.choice(["cafe","park","grocery","library","gym","restaurant"]) ,
    }
    if prefs:
        base_prefs.update(prefs)

    return AgentPersona(id=agent_id, role=role, name=f"{first} {last}", traits=traits, prefs=base_prefs)


def init_agent(run_id: str, agent_id: str, role: str, seed: Optional[int] = None, prefs: Optional[Dict[str, str]] = None) -> AgentState:
    _ensure_cache(run_id)
    if agent_id in _CACHE[run_id]:
        return _CACHE[run_id][agent_id]
    persona = create_persona(agent_id, role, seed, prefs)
    state = AgentState(id=agent_id, persona=persona, last_intent=None, memories=[])
    # ensure dirs
    os.makedirs(_agent_dir(run_id, agent_id), exist_ok=True)
    _CACHE[run_id][agent_id] = state
    return state


def get_state(run_id: str, agent_id: str) -> Optional[AgentState]:
    _ensure_cache(run_id)
    st = _CACHE[run_id].get(agent_id)
    if st is None:
        # Try to lazily load last persona if exists
        mem_path = _mem_path(run_id, agent_id)
        if os.path.exists(mem_path):
            # Load persona if present in first line with kind=="persona"
            persona = None
            memories: List[MemoryEvent] = []
            with open(mem_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                        if obj.get("kind") == "persona" and not persona:
                            persona = AgentPersona(**obj["persona"])  # type: ignore
                        else:
                            memories.append(MemoryEvent(**obj))
                    except Exception:
                        continue
            if persona:
                st = AgentState(id=agent_id, persona=persona, memories=memories)
                _CACHE[run_id][agent_id] = st
    return st


def append_memory(run_id: str, agent_id: str, ev: MemoryEvent):
    os.makedirs(_agent_dir(run_id, agent_id), exist_ok=True)
    with open(_mem_path(run_id, agent_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(ev.model_dump(), ensure_ascii=False) + "\n")
    st = get_state(run_id, agent_id)
    if st:
        st.memories.append(ev)


def persist_persona(run_id: str, agent_id: str, persona: AgentPersona):
    os.makedirs(_agent_dir(run_id, agent_id), exist_ok=True)
    rec = {"ts": _now_iso(), "kind": "persona", "persona": persona.model_dump()}
    with open(_mem_path(run_id, agent_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


