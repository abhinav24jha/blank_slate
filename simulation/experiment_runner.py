#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Headless experiment runner: baseline vs scenarios.

v1 scope: generate scenario assets (POIs), start a run, register biased snapshots,
request one round of decisions, and write a tiny metrics summary. This validates
the pipeline end-to-end before adding full stepping/pathing.
"""

from __future__ import annotations
import os, json, time, uuid, random
from typing import List, Dict, Tuple
import requests

from .scenario_models import ExperimentConfig
from .environment_editor import apply_scenario_to_assets
from .needs_and_objectives import build_need_biases_for_scenario, inject_bias_into_snapshot


BRAIN = "http://127.0.0.1:9000"


def _read_json(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, obj: Dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


def _load_navgraph(assets_dir: str) -> Tuple["np.ndarray","np.ndarray"]:
    import numpy as np
    nz = os.path.join(assets_dir, "navgraph.npz")
    data = np.load(nz)
    walkable = data["walkable"].astype(np.uint8)
    cost = data["cost"].astype(np.uint8)
    return walkable, cost


def _nearest_path_len(assets_dir: str, category: str, start_iy: int, start_ix: int) -> float:
    """Compute A* path length in grid steps to nearest POI of category. Returns inf if none."""
    import numpy as np
    from .nav_and_pois import astar

    with open(os.path.join(assets_dir, "pois.json"), "r", encoding="utf-8") as f:
        pois = json.load(f)
    walkable, cost = _load_navgraph(assets_dir)
    H, W = walkable.shape
    best = float("inf")
    for p in pois:
        if p.get("type") != category:
            continue
        loc = p.get("snapped") or {"iy": p.get("iy"), "ix": p.get("ix")}
        if loc is None: continue
        gy, gx = int(loc["iy"]), int(loc["ix"]) 
        if not (0<=gx<W and 0<=gy<H):
            continue
        path = astar(cost, walkable, (start_iy, start_ix), (gy, gx))
        if path:
            best = min(best, float(len(path)))
    return best


def run_single_scenario(exp_id: str, scenario_path: str, cfg: ExperimentConfig) -> Dict:
    sc = _read_json(scenario_path)
    sc_id = sc["id"]
    out_dir = os.path.join(cfg.exp_out_dir, exp_id, sc_id)
    os.makedirs(out_dir, exist_ok=True)

    # 1) Apply scenario to assets (POIs only)
    assets_out = os.path.join(out_dir, "assets")
    apply_scenario_to_assets(cfg.baseline_dir, scenario_path, assets_out)

    # 2) Warmup + start run
    try:
        requests.post(f"{BRAIN}/warmup", timeout=60)
    except Exception:
        pass
    r = requests.post(f"{BRAIN}/start_run", json={"hypothesisId": sc_id, "seed": cfg.seed, "speed": cfg.speed}, timeout=120)
    r.raise_for_status()
    run_id = r.json()["runId"]

    # 3) Create simple synthetic agent snapshots positioned in the center
    walk = os.path.join(assets_out, "walkable.npy")
    import numpy as np
    walkable = np.load(walk)
    H, W = walkable.shape
    cy, cx = H//2, W//2

    agents = []
    roles = ["student", "resident", "worker"]
    random.seed(cfg.seed)
    for i in range(cfg.agent_count):
        agents.append({
            "id": f"E{i}",
            "role": random.choice(roles),
            "pos": [float(cx), float(cy)],
            "needs": {"caffeine": 0.4, "social": 0.4, "hunger": 0.4}
        })

    # 4) Build biases and request an initial decision batch
    from .scenario_models import Scenario
    s = Scenario.model_validate_json(json.dumps(sc))
    biases = build_need_biases_for_scenario(s)
    snaps = [inject_bias_into_snapshot(a, biases) for a in agents]

    decisions: List[Dict] = []
    try:
        r = requests.post(f"{BRAIN}/decide", json={
            "runId": run_id,
            "agents": snaps,
            "context": {"scenario_id": sc_id, "biases": biases}
        }, timeout=120)
        r.raise_for_status()
        decisions = r.json().get("decisions", [])
    except Exception as e:
        # Fallback: sample categories from biases or default set
        cats = list(biases.keys()) or ["cafe","grocery","restaurant","retail"]
        weights = [biases.get(c, 0.25) for c in cats]
        s = sum(weights) or 1.0
        weights = [w/s for w in weights]
        for a in agents:
            cat = random.choices(cats, weights=weights, k=1)[0]
            decisions.append({"id": a["id"], "next_intent": {"category": cat}, "thought": f"Heading to {cat}."})

    # 5) Tiny metrics summary
    by_cat: Dict[str,int] = {}
    for d in decisions:
        cat = (d.get("next_intent") or {}).get("category") or "unknown"
        by_cat[cat] = by_cat.get(cat, 0) + 1

    # 6) Distance delta vs baseline to nearest POI for chosen category
    import numpy as np
    walkable = np.load(os.path.join(assets_out, "walkable.npy"))
    H, W = walkable.shape
    cy, cx = H//2, W//2
    deltas: Dict[str, List[float]] = {}
    for d in decisions:
        cat = (d.get("next_intent") or {}).get("category")
        if not cat: continue
        dist_s = _nearest_path_len(assets_out, cat, cy, cx)
        dist_b = _nearest_path_len(cfg.baseline_dir, cat, cy, cx)
        if np.isfinite(dist_s) and np.isfinite(dist_b):
            deltas.setdefault(cat, []).append(float(dist_b - dist_s))

    avg_delta = {k: (sum(v)/len(v) if v else 0.0) for k, v in deltas.items()}

    summary = {
        "run_id": run_id,
        "scenario": sc_id,
        "agent_count": len(agents),
        "decisions": len(decisions),
        "by_category": by_cat,
        "avg_distance_saved_steps": avg_delta
    }
    _write_json(os.path.join(out_dir, "metrics_summary.json"), summary)
    return summary


def run_experiment(exp_id: str, scenario_paths: List[str], cfg: ExperimentConfig) -> Dict:
    all_summaries = {}
    for p in scenario_paths:
        all_summaries[os.path.basename(p)] = run_single_scenario(exp_id, p, cfg)
    return all_summaries


if __name__ == "__main__":
    cfg = ExperimentConfig()
    exp_id = str(uuid.uuid4())[:8]
    scenarios = [
        "simulation/scenarios/baseline.json",
        "simulation/scenarios/society145_h001_convenience_cafe.json"
    ]
    # Ensure brain server is up; warmup helps cold start
    try:
        requests.post(f"{BRAIN}/warmup", timeout=60)
    except Exception:
        pass
    out = run_experiment(exp_id, scenarios, cfg)
    print(json.dumps(out, indent=2))


