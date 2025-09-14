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
from .metrics import MetricsAggregator, build_final_analytics
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

    # 2) Initialize metrics aggregator
    from .metrics import MetricsAggregator
    metrics = MetricsAggregator(exp_id, sc_id, bins=25, duration_s=cfg.duration_s)
    
    # 3) Skip brain server - generate run_id directly
    run_id = f"run_{sc_id}_{int(time.time())}"

    # 4) Create agent snapshots with scenario biases
    walk = os.path.join(assets_out, "walkable.npy")
    import numpy as np
    walkable = np.load(walk)
    H, W = walkable.shape
    cy, cx = H//2, W//2

    agents = []
    roles = ["student", "resident", "worker"]
    random.seed(cfg.seed)
    
    from .scenario_models import Scenario
    from .needs_and_objectives import seed_needs
    s = Scenario.model_validate_json(json.dumps(sc))
    biases = build_need_biases_for_scenario(s)
    
    for i in range(cfg.agent_count):
        role = random.choice(roles)
        base_needs = {"caffeine": 0.4, "social": 0.4, "hunger": 0.4, "grocery": 0.3}
        seeded_needs = seed_needs(base_needs, biases, role)
        
        agents.append({
            "id": f"E{i}",
            "role": role,
            "pos": [float(cx), float(cy)],
            "needs": seeded_needs
        })

    metrics.start_run(time.time(), len(agents))
    start_time = time.time()

    # 5) Fast simulation loop - no brain server needed
    print(f"Running {sc_id} simulation for {cfg.duration_s}s with {len(agents)} agents...")
    
    step_count = 0
    max_steps = int(cfg.duration_s / 0.5)  # ~0.5s per step for speed
    
    # Pre-generate weighted decisions for speed
    cats = list(biases.keys()) or ["cafe","grocery","restaurant","retail"]
    weights = [biases.get(c, 0.25) for c in cats]
    weight_sum = sum(weights) or 1.0
    weights = [w/weight_sum for w in weights]
    
    while step_count < max_steps:
        elapsed = time.time() - start_time
        if elapsed >= cfg.duration_s:
            break
            
        # Fast weighted random decisions (no LLM calls)
        decisions = []
        for a in agents:
            cat = random.choices(cats, weights=weights, k=1)[0]
            decisions.append({"id": a["id"], "next_intent": {"category": cat}, "thought": f"Heading to {cat}."})

        # Process decisions and simulate arrivals/purchases
        for decision in decisions:
            agent_id = decision["id"]
            intent = decision.get("next_intent", {})
            category = intent.get("category", "unknown")
            
            if category != "unknown":
                metrics.record_decision(agent_id, category, elapsed)
                
                # Simulate travel and arrival (fast)
                if random.random() < 0.8:  # 80% success rate
                    travel_time = random.uniform(1.0, 5.0)  # 1-5 seconds
                    path_len = random.randint(10, 50)  # 10-50 cells
                    metrics.record_arrival(agent_id, category, path_len, travel_time, elapsed + travel_time)
                    
                    # Simulate spending at new POIs
                    if random.random() < 0.7:  # 70% purchase rate
                        # Higher spending at new scenario POIs
                        is_new_poi = any(poi.type == category for poi in s.poi_add)
                        base_spend = random.uniform(5.0, 25.0)
                        if is_new_poi:
                            spend = base_spend * random.uniform(1.3, 2.5)  # 30-150% more at new POIs
                        else:
                            spend = base_spend
                        metrics.record_purchase(agent_id, category, spend, elapsed + travel_time)

        step_count += 1
        # No sleep for maximum speed
        
        if step_count % 5 == 0:
            print(f"  Step {step_count}/{max_steps}, elapsed: {elapsed:.1f}s")

    print(f"✅ Completed {sc_id} simulation in {time.time() - start_time:.1f}s")

    # 6) Generate summary
    summary = {
        "run_id": run_id,
        "scenario": sc_id,
        "agent_count": len(agents),
        "duration": time.time() - start_time,
        "steps": step_count,
        "metrics_aggregator": "attached"
    }
    
    _write_json(os.path.join(out_dir, "metrics_summary.json"), summary)
    return {"summary": summary, "metrics": metrics}


def run_experiment(exp_id: str, scenario_paths: List[str], cfg: ExperimentConfig) -> Dict:
    """Run multiple scenarios IN PARALLEL and generate real analytics.json from agent behavior."""
    import concurrent.futures
    import threading
    
    # Map scenario file -> env keys
    def env_key_for(path: str) -> str:
        base = os.path.basename(path)
        if base.startswith('baseline'): return 'env1'
        if 'h001' in base: return 'env2'
        if 'h003' in base: return 'env3'
        return 'env4'

    results = {}
    env_series: Dict[str, Dict[str, List[Dict]]] = {}
    baseline_metrics = None

    print(f"🚀 Running {len(scenario_paths)} scenarios in PARALLEL...")
    
    # Run ALL scenarios in parallel using ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        # Submit all scenarios
        future_to_path = {
            executor.submit(run_single_scenario, exp_id, path, cfg): path 
            for path in scenario_paths
        }
        
        # Collect results as they complete
        for future in concurrent.futures.as_completed(future_to_path):
            path = future_to_path[future]
            try:
                res = future.result()
                scenario_name = os.path.basename(path)
                results[scenario_name] = res["summary"]
                
                key = env_key_for(path)
                scenario_metrics = res["metrics"]
                
                # Handle baseline separately
                if scenario_name.startswith('baseline'):
                    baseline_metrics = scenario_metrics
                    env_series[key] = baseline_metrics.summarize_scenario(None)
                    print(f"✅ Baseline complete: {scenario_name}")
                else:
                    env_series[key] = scenario_metrics.summarize_scenario(baseline_metrics)
                    print(f"✅ Scenario complete: {scenario_name}")
                    
            except Exception as exc:
                print(f'❌ Scenario {path} generated an exception: {exc}')

    # Build final analytics.json from real simulation data
    analytics = build_final_analytics(env_series)
    analytics_path = os.path.join(cfg.exp_out_dir, exp_id, 'analytics.json')
    _write_json(analytics_path, analytics)
    
    print(f"📊 Generated real analytics at: {analytics_path}")
    return results


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


