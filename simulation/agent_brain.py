#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM-backed reasoning helpers for intent and chat, using local Ollama.
"""

from __future__ import annotations
from typing import Tuple, Dict
from .agent_schemas import AgentState
from .llm_clients.ollama_client import call_json


INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": [
            "grocery", "pharmacy", "cafe", "restaurant", "education", "health", "retail", "transit", "leisure"
        ]},
        "thought": {"type": "string"},
        "memory": {"type": "string"}
    },
    "required": ["category"]
}


def llm_decide_intent(model: str, state: AgentState, snapshot: Dict, context: Dict) -> Tuple[str, str, str]:
    """Select next high-level destination category with human-like rationale."""
    mem_lines = "\n".join(f"- {m.text}" for m in state.recent(6))
    top_needs = sorted((snapshot.get("needs") or {}).items(), key=lambda x: -x[1])
    needs_str = ", ".join(f"{k}:{v:.2f}" for k, v in top_needs[:3])
    tod = context.get("time_of_day") or snapshot.get("time_of_day") or "unknown"
    role = snapshot.get("role") or state.persona.role

    scenario_id = context.get("scenario_id")
    biases = context.get("biases", {})

    system = (
        "You are an on-device simulation agent deciding a realistic next stop. "
        "Always return STRICT JSON only (no prose) matching the provided schema. "
        "Use persona, recent memories, and top needs. Keep thought first-person, short, and specific."
    )

    prompt = (
        "Decide a destination category from: grocery, pharmacy, cafe, restaurant, education, health, retail, transit, leisure.\n"
        f"Persona: {state.persona.compact()}\n"
        f"Role: {role}\n"
        f"Time of day: {tod}\n"
        f"Top needs (high→low): {needs_str or '—'}\n"
        f"Recent memories (latest first):\n{mem_lines or '- none -'}\n"
        + (f"Scenario: {scenario_id}. Suggested emphasis by category: {biases}.\n" if scenario_id or biases else "")
        + "Constraints:\n"
        "- Pick ONE category only, consistent with needs and role/time.\n"
        "- thought: <= 20 words, first-person, natural (e.g., 'I need a quick coffee before class.').\n"
        "- memory: <= 18 words, a concise first-person summary of the choice (e.g., 'Chose a cafe near campus to wake up.')."
    )

    out = call_json(model, system, prompt, INTENT_SCHEMA, temperature=0.4)
    cat = out.get("category", "retail")
    thought = out.get("thought", "")
    memory = out.get("memory", f"Chose {cat}.")
    return cat, thought, memory


CHAT_SCHEMA = {
    "type": "object",
    "properties": {
        "a_line": {"type": "string"},
        "b_line": {"type": "string"},
        "mem_a": {"type": "string"},
        "mem_b": {"type": "string"}
    },
    "required": ["a_line", "b_line"]
}


def llm_chat(model: str, a_state: AgentState, b_state: AgentState, context: Dict) -> Dict:
    """Generate a brief, varied two-line exchange tailored to each persona and context."""
    a_mem = "\n".join(f"- {m.text}" for m in a_state.recent(4))
    b_mem = "\n".join(f"- {m.text}" for m in b_state.recent(4))
    topic = context.get("topic", "a nearby spot")
    time_of_day = context.get("time_of_day", "")

    system = (
        "Write two natural, distinct lines of dialogue for a brief meeting. "
        "Return STRICT JSON only. Avoid generic greetings; vary diction using traits/prefs."
    )

    prompt = (
        f"A persona: {a_state.persona.compact()}\n"
        f"A recent memories:\n{a_mem or '- none -'}\n\n"
        f"B persona: {b_state.persona.compact()}\n"
        f"B recent memories:\n{b_mem or '- none -'}\n\n"
        f"Context: They bump into each other at {topic}{' around ' + time_of_day if time_of_day else ''}.\n"
        "Guidelines:\n"
        "- Exactly one line for A and one for B.\n"
        "- <= 16 words per line.\n"
        "- If plausible, touch on a shared interest or current need; otherwise note surroundings.\n"
        "- No stage directions, no quotes, no emojis.\n"
        "- mem_a/mem_b: first-person takeaways (<= 14 words)."
    )

    out = call_json(model, system, prompt, CHAT_SCHEMA, temperature=0.5)
    return {
        "a_line": out.get("a_line", "Hi."),
        "b_line": out.get("b_line", "Hello."),
        "mem_a": out.get("mem_a", f"Chatted with {b_state.persona.name} about {topic}"),
        "mem_b": out.get("mem_b", f"Chatted with {a_state.persona.name} about {topic}"),
    }


