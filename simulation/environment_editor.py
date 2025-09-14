#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Apply Scenario diffs to baseline assets to produce scenario-specific assets.

Scope v1: POI add/update only. We reuse the baseline navgraph and grids.
"""

from __future__ import annotations
import os, json, shutil
from typing import Dict, Tuple

import numpy as np

from .scenario_models import Scenario, POIDef


def _load_baseline_assets(baseline_dir: str) -> Dict:
    with open(os.path.join(baseline_dir, "pois.json"), "r", encoding="utf-8") as f:
        pois = json.load(f)
    walk = np.load(os.path.join(baseline_dir, "walkable.npy"))
    return {"pois": pois, "walkable": walk}


def _resolve_anchor(anchor_name: str, walkable: np.ndarray) -> Tuple[int,int]:
    H, W = walkable.shape
    if anchor_name == "center" or anchor_name == "frontage_center":
        # Approximate center of the map for first pass. Caller can tune dx/dy.
        return H//2, W//2
    # Fallback to map center
    return H//2, W//2


def _place_poi(defn: POIDef, walkable: np.ndarray) -> Tuple[int,int]:
    if defn.iy is not None and defn.ix is not None:
        return int(defn.iy), int(defn.ix)
    assert defn.anchor is not None
    ay, ax = _resolve_anchor(defn.anchor.name, walkable)
    return int(max(0, min(walkable.shape[0]-1, ay + defn.anchor.dy))), int(max(0, min(walkable.shape[1]-1, ax + defn.anchor.dx)))


def apply_scenario_to_assets(baseline_dir: str, scenario_path: str, out_dir: str) -> Dict:
    os.makedirs(out_dir, exist_ok=True)
    # Copy navgraph/grids directly (no topology edits in v1)
    for fname in ("semantic.npy", "walkable.npy", "cost.npy", "feature_id.npy", "navgraph.npz", "labels.json", "feature_table.json"):
        src = os.path.join(baseline_dir, fname)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out_dir, fname))

    assets = _load_baseline_assets(baseline_dir)
    walkable = assets["walkable"]
    with open(scenario_path, "r", encoding="utf-8") as f:
        sc = Scenario.model_validate_json(f.read())

    # Start from baseline POIs
    pois = list(assets["pois"])

    # Apply adds
    for pd in sc.poi_add:
        iy, ix = _place_poi(pd, walkable)
        # Snap to walkable if target cell isn't walkable
        if not (0 <= ix < walkable.shape[1] and 0 <= iy < walkable.shape[0]) or walkable[iy, ix] == 0:
            # naive outward search within 20 cells
            found = None
            for r in range(1, 21):
                y0, y1 = max(0, iy-r), min(walkable.shape[0]-1, iy+r)
                x0, x1 = max(0, ix-r), min(walkable.shape[1]-1, ix+r)
                sub = np.argwhere(walkable[y0:y1+1, x0:x1+1] == 1)
                if sub.size:
                    vy, vx = sub[0]
                    found = (y0+int(vy), x0+int(vx)); break
            if found: iy, ix = found
        pois.append({
            "type": pd.type,
            "iy": int(iy), "ix": int(ix),
            "name": pd.name,
            "tags": pd.attrs or {},
            "snapped": {"iy": int(iy), "ix": int(ix)}
        })

    # Apply updates (simple matcher)
    def _matches(p: Dict, match: Dict) -> bool:
        for k, v in match.items():
            if p.get(k) != v: return False
        return True

    for upd in sc.poi_update:
        for p in pois:
            if _matches(p, upd.match):
                for k, v in (upd.set or {}).items():
                    if k == "tags" and isinstance(v, dict):
                        tags = p.get("tags") or {}
                        tags.update(v); p["tags"] = tags
                    else:
                        p[k] = v

    # Write pois.json
    with open(os.path.join(out_dir, "pois.json"), "w", encoding="utf-8") as f:
        json.dump(pois, f, indent=2)

    # Simple overlay for debug: mark added POIs in green
    summary = {"poi_count": len(pois), "added": len(sc.poi_add)}
    with open(os.path.join(out_dir, "feature_table.json"), "a", encoding="utf-8") as _:
        pass
    return summary


if __name__ == "__main__":
    BASE = "out/society145_1km"
    SC = "simulation/scenarios/society145_h001_convenience_cafe.json"
    OUT = "simulation/out/scenario_preview"
    s = apply_scenario_to_assets(BASE, SC, OUT)
    print(json.dumps(s, indent=2))


