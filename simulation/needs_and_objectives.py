#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scenario-driven need biases and simple objective helpers.
"""

from __future__ import annotations
from typing import Dict
from .scenario_models import Scenario


def build_need_biases_for_scenario(s: Scenario) -> Dict[str, float]:
    """Return category->weight in [0,1] to bias early decisions toward scenario POIs."""
    # Use tags.bias if provided; otherwise infer from added POIs
    bias = dict(s.tags.get("bias", {})) if s.tags else {}
    if not bias:
        for pd in s.poi_add:
            bias[pd.type] = max(0.2, bias.get(pd.type, 0.0) + 0.2)
    # normalize to [0,1]
    for k, v in list(bias.items()):
        bias[k] = max(0.0, min(1.0, float(v)))
    return bias


def inject_bias_into_snapshot(snapshot: Dict, biases: Dict[str, float]) -> Dict:
    """Return a copy of snapshot with needs boosted per biases.

    The viewer/runner can pass this snapshot to the brain for first decisions.
    """
    snap = {**snapshot}
    needs = dict((snap.get("needs") or {}))
    for cat, w in biases.items():
        needs[cat] = max(needs.get(cat, 0.0), w)
    snap["needs"] = needs
    return snap


def seed_needs(snapshot_needs: Dict, biases: Dict[str, float], role: str) -> Dict:
    """Return a seeded needs dict that emphasizes scenario categories but keeps plausible values."""
    needs = dict(snapshot_needs or {})
    # base floor by role
    floors = {
        'student': {'education': 0.5, 'cafe': 0.4},
        'resident': {'grocery': 0.4},
        'worker': {'cafe': 0.3}
    }
    for k, v in floors.get(role, {}).items():
        needs[k] = max(needs.get(k, 0.0), v)
    for cat, w in biases.items():
        needs[cat] = max(needs.get(cat, 0.0), min(1.0, w + 0.2))
    return needs


def decay_and_reinforce(needs: Dict[str, float], dt: float, biases: Dict[str, float]) -> Dict[str, float]:
    out = dict(needs)
    # decay all slightly
    for k in list(out.keys()):
        out[k] = max(0.0, out[k] - 0.02 * dt)
    # reinforce biased categories
    for k, w in biases.items():
        out[k] = min(1.0, max(out.get(k, 0.0), w - 0.1*dt))
    return out


def scenario_objective_mask(scenario_id: str) -> set[str]:
    if 'h001' in scenario_id: return {'grocery','pharmacy','cafe'}
    if 'h003' in scenario_id: return {'restaurant','cafe'}
    return set()


