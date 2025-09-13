#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Export a placeholder tile atlas and tile grid from Step 2/3 outputs for a web viewer.

Outputs under: {out_dir}/tiles/
- atlas.png                : packed placeholder tiles (variants per class)
- manifest.json            : viewer manifest with atlas frames and grid metadata
- tile_grid.bin            : uint16 tile indices (with header)

Tile indexing:
  tile_index = class_id * VARIANTS + variant_id
Variant choice per cell is deterministic using (y, x, class_id) hash.

Note: This exporter creates placeholder visuals based on the class palette.
      Replace atlas later with NanoBanana-generated tiles while keeping the
      same atlas.json layout and tile indices to avoid changing the viewer.
"""

from __future__ import annotations
import os, json, struct, hashlib, math
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image

# Semantic classes (must match osm_to_grid.py)
VOID, BUILDING, SIDEWALK, FOOTPATH, PARKING, PLAZA, GREEN, WATER, ROAD, CROSSING = range(10)
CLASS_NAMES = {
    VOID:"void", BUILDING:"building", SIDEWALK:"sidewalk", FOOTPATH:"footpath",
    PARKING:"parking", PLAZA:"plaza", GREEN:"green", WATER:"water", ROAD:"road", CROSSING:"crossing"
}
PALETTE = {
    VOID:(240,240,240), BUILDING:(60,60,60), SIDEWALK:(230,230,230), FOOTPATH:(200,200,200),
    PARKING:(210,210,160), PLAZA:(235,215,160), GREEN:(140,190,140), WATER:(150,180,220),
    ROAD:(120,120,120), CROSSING:(250,250,120)
}

VARIANTS = 3
TILE_SIZE = 16  # pixels per cell (viewer can rescale)


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _seeded_rand(y: int, x: int, cls: int) -> float:
    # Deterministic small noise per cell
    h = hashlib.blake2b(f"{y},{x},{cls}".encode("utf-8"), digest_size=8).digest()
    val = int.from_bytes(h, "little")
    return (val % 10000) / 10000.0


def _variant_for_cell(y: int, x: int, cls: int, semantic: np.ndarray = None) -> int:
    # Smart variant selection for buildings, random for others
    if cls == BUILDING and semantic is not None:
        # Check if this building cell is near an edge (potential entrance)
        H, W = semantic.shape
        is_edge = False
        for dy, dx in [(-1,0), (1,0), (0,-1), (0,1)]:  # 4-neighbor check
            ny, nx = y + dy, x + dx
            if 0 <= ny < H and 0 <= nx < W:
                if semantic[ny, nx] != BUILDING:  # Adjacent to non-building
                    is_edge = True
                    break
        
        if is_edge:
            # Edge cells: 70% variant 0 (basic), 25% variant 1 (door), 5% variant 2 (corner)
            h = (y * 73856093) ^ (x * 19349663)
            rand_val = abs(h) % 100
            if rand_val < 25:
                return 1  # Door variant
            elif rand_val < 30:
                return 2  # Corner variant
            else:
                return 0  # Basic variant
        else:
            # Interior cells: mostly basic, some corner
            h = (y * 73856093) ^ (x * 19349663)
            return 0 if (abs(h) % 10) < 8 else 2  # 80% basic, 20% corner
    
    # Default random selection for non-buildings
    h = (y * 73856093) ^ (x * 19349663) ^ (cls * 83492791)
    return abs(h) % VARIANTS


def _shade(color: Tuple[int,int,int], factor: float) -> Tuple[int,int,int]:
    r,g,b = color
    r = max(0, min(255, int(round(r * factor))))
    g = max(0, min(255, int(round(g * factor))))
    b = max(0, min(255, int(round(b * factor))))
    return (r,g,b)


def build_placeholder_atlas(out_tiles_dir: str) -> Dict:
    """Create a simple atlas with VARIANTS tiles per class, save atlas.png and return frames metadata."""
    classes = [CLASS_NAMES[i] for i in range(10)]
    cols = VARIANTS
    rows = len(classes)
    W = cols * TILE_SIZE
    H = rows * TILE_SIZE

    img = Image.new("RGB", (W, H), (0,0,0))

    frames: List[Dict] = []
    for row, class_id in enumerate(range(10)):
        base = PALETTE[class_id]
        # Variant shading factors to avoid flatness
        factors = [0.95, 1.00, 1.05][:VARIANTS]
        for col in range(VARIANTS):
            x0 = col * TILE_SIZE
            y0 = row * TILE_SIZE
            # Fill with shaded color plus tiny checker to hint texture
            shade = _shade(base, factors[col])
            tile = Image.new("RGB", (TILE_SIZE, TILE_SIZE), shade)
            px = tile.load()
            for yy in range(TILE_SIZE):
                for xx in range(TILE_SIZE):
                    if ((xx ^ yy) & 3) == 0:  # sparse pattern
                        # subtle noise
                        k = 0.97 + 0.06 * (((xx*31 + yy*17 + class_id*13 + col*7) % 100) / 100.0)
                        rr, gg, bb = px[xx, yy]
                        px[xx, yy] = (
                            max(0, min(255, int(rr * k))),
                            max(0, min(255, int(gg * k))),
                            max(0, min(255, int(bb * k))),
                        )
            img.paste(tile, (x0, y0))

            frames.append({
                "name": f"{CLASS_NAMES[class_id]}_v{col}",
                "class": CLASS_NAMES[class_id],
                "class_id": class_id,
                "variant": col,
                "x": x0, "y": y0, "w": TILE_SIZE, "h": TILE_SIZE,
                "tile_index": class_id * VARIANTS + col,
            })

    atlas_path = os.path.join(out_tiles_dir, "atlas.png")
    img.save(atlas_path)
    return {
        "image": "atlas.png",
        "width": W,
        "height": H,
        "frames": frames,
    }


def build_tile_grid(semantic: np.ndarray) -> np.ndarray:
    H, W = semantic.shape
    grid = np.zeros((H, W), dtype=np.uint16)
    # Fill by class; compute variant deterministically with semantic awareness
    for y in range(H):
        row = semantic[y]
        for x in range(W):
            cls = int(row[x])
            if cls < 0 or cls > 9:
                cls = VOID
            v = _variant_for_cell(y, x, cls, semantic)  # Pass semantic for smart building selection
            grid[y, x] = cls * VARIANTS + v
    return grid


def save_tile_grid_binary(path: str, grid: np.ndarray) -> None:
    H, W = grid.shape
    with open(path, "wb") as f:
        # Header: magic(4) + version(u16) + width(u32) + height(u32) + tileSize(u16)
        f.write(b"TGRD")
        f.write(struct.pack("<H", 1))
        f.write(struct.pack("<I", W))
        f.write(struct.pack("<I", H))
        f.write(struct.pack("<H", TILE_SIZE))
        # Payload: uint16 little-endian row-major
        f.write(grid.astype(np.uint16).tobytes(order="C"))


def export(out_dir: str) -> Dict:
    tiles_dir = os.path.join(out_dir, "tiles")
    _ensure_dir(tiles_dir)

    # Load arrays
    semantic = np.load(os.path.join(out_dir, "semantic.npy"))
    nav = np.load(os.path.join(out_dir, "navgraph.npz"))
    walkable = nav["walkable"]
    cost = nav["cost"]
    origin = nav["origin"].astype(float).tolist()
    cell_m = float(nav["cell_m"][0]) if nav["cell_m"].shape else float(nav["cell_m"])  # robust

    H, W = semantic.shape

    # Build atlas
    atlas = build_placeholder_atlas(tiles_dir)

    # Build tile grid
    tile_grid = build_tile_grid(semantic)
    save_tile_grid_binary(os.path.join(tiles_dir, "tile_grid.bin"), tile_grid)

    # Manifest
    manifest = {
        "tileSize": TILE_SIZE,
        "variants": VARIANTS,
        "classes": [CLASS_NAMES[i] for i in range(10)],
        "class_to_base_index": {CLASS_NAMES[i]: i*VARIANTS for i in range(10)},
        "atlas": atlas,
        "grid": {
            "binary": "tile_grid.bin",
            "format": "LE_uint16_rowmajor_TGRD_v1",
            "width": W,
            "height": H,
        },
        "physics": {
            "walkable": "../navgraph.npz#walkable",
            "cost": "../navgraph.npz#cost",
            "origin": origin,
            "cell_m": cell_m,
            "pois": "../pois.json",
        },
    }

    with open(os.path.join(tiles_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return {
        "tiles_dir": tiles_dir,
        "W": W, "H": H,
        "tile_count": int(tile_grid.size),
        "variants": VARIANTS,
        "tile_size": TILE_SIZE,
    }


if __name__ == "__main__":
    OUT = os.path.join("out", "society145_1km")
    info = export(OUT)
    print(json.dumps(info, indent=2))
