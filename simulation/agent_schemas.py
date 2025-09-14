#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Typed schemas shared across the brain server modules.
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Dict, List, Optional


class AgentPersona(BaseModel):
    id: str
    role: str
    name: str
    traits: List[str] = Field(default_factory=list)
    prefs: Dict[str, str] = Field(default_factory=dict)

    def compact(self) -> str:
        t = ", ".join(self.traits[:5]) if self.traits else "—"
        p = ", ".join(f"{k}:{v}" for k, v in list(self.prefs.items())[:6]) if self.prefs else "—"
        return f"{self.name} ({self.role}); traits: {t}; prefs: {p}"


class MemoryEvent(BaseModel):
    ts: str
    kind: str  # decision|chat|meeting|observation|trip
    text: str
    tags: List[str] = Field(default_factory=list)


class AgentState(BaseModel):
    id: str
    persona: AgentPersona
    last_intent: Optional[str] = None
    memories: List[MemoryEvent] = Field(default_factory=list)

    def recent(self, k: int = 6) -> List[MemoryEvent]:
        return self.memories[-k:]


class AgentSnapshot(BaseModel):
    id: str
    role: str
    pos: List[float]
    needs: Dict[str, float]
    time_of_day: Optional[str] = None


class NextIntent(BaseModel):
    category: str
    name: Optional[str] = None


class Decision(BaseModel):
    id: str
    next_intent: NextIntent
    thought: Optional[str] = None
    chat: Optional[str] = None


