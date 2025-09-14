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


