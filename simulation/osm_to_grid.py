#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 2 — OSM → Physics Grid (fast, with radius expansion + feature_id)

Public entrypoint:
    run_step2_from_step1(step1: dict, out_dir: str, cell_m: float = 1.5, radius_m: float | None = None) -> dict

Outputs (to out_dir):
    - semantic.npy (uint8)   # class per cell
    - walkable.npy (uint8)   # 0/1
    - cost.npy (uint8)       # 255 = blocked
    - feature_id.npy (int32) # polygon id or -1 where none
    - feature_table.json     # metadata for polygon ids
    - semantic_preview.png   # colorized sanity check

Requires: requests, shapely, pyproj, numpy, pillow, rasterio
"""

from __future__ import annotations
import os, math, json, logging
from typing import Dict, List, Tuple
import requests
import numpy as np
from dataclasses import dataclass
from PIL import Image

from shapely.geometry import shape, LineString, Point
from shapely.ops import transform
import shapely
import pyproj
from rasterio import features as rfeat
from rasterio.enums import MergeAlg

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
UA = {"User-Agent": "agent-sim-geo/1.0 (fast rasterio; debug enabled)"}
OVERPASS = "https://overpass-api.de/api/interpreter"

# ---------- Semantic classes ----------
VOID, BUILDING, SIDEWALK, FOOTPATH, PARKING, PLAZA, GREEN, WATER, ROAD, CROSSING = range(10)
CLASS_NAMES = {
    VOID:"void", BUILDING:"building", SIDEWALK:"sidewalk", FOOTPATH:"footpath",
    PARKING:"parking", PLAZA:"plaza", GREEN:"green", WATER:"water", ROAD:"road", CROSSING:"crossing"
}
PALETTE = {
    VOID:(240,240,240), BUILDING:(60,60,60), SIDEWALK:(230,230,230),
    FOOTPATH:(200,200,200), PARKING:(210,210,160), PLAZA:(235,215,160),
    GREEN:(140,190,140), WATER:(150,180,220), ROAD:(120,120,120), CROSSING:(250,250,120)
}

# ---------- Tag → class ----------
def class_for(tags: Dict, geom_type: str) -> int:
    if "building" in tags: return BUILDING
    if tags.get("highway") in ("footway","path","steps","pedestrian"):
        return SIDEWALK if tags.get("footway") == "sidewalk" else FOOTPATH
    if tags.get("footway") == "crossing": return CROSSING
    if tags.get("highway") in ("residential","service","tertiary","secondary","primary","unclassified"):
        return ROAD
    if tags.get("amenity") == "parking" or tags.get("landuse") == "parking": return PARKING
    if tags.get("landuse") in ("retail","commercial"): return PLAZA
    if tags.get("natural") in ("wood","tree","scrub","grassland") or tags.get("landuse") in ("grass","meadow","recreation_ground"):
        return GREEN
    if tags.get("waterway") or tags.get("natural") == "water": return WATER
    return VOID

# ---------- Overpass ----------
def fetch_osm(bbox: Tuple[float,float,float,float]) -> Dict:
    s, w, n, e = bbox
    query = f"""
    [out:json][timeout:60];
    (
      way["building"]({s},{w},{n},{e});
      way["highway"]({s},{w},{n},{e});
      way["amenity"]({s},{w},{n},{e});
      way["landuse"]({s},{w},{n},{e});
      way["natural"]({s},{w},{n},{e});
      way["waterway"]({s},{w},{n},{e});
      node["amenity"]({s},{w},{n},{e});
    );
    (._;>;);
    out body;
    """
    logging.info("[step2] Overpass fetch bbox=%s", bbox)
    r = requests.post(OVERPASS, data=query, headers=UA, timeout=90)
    r.raise_for_status()
    js = r.json()
    logging.info("[step2] Overpass elements=%d", len(js.get("elements", [])))
    return js

# ---------- Normalize to shapely (projected) ----------
@dataclass
class OSMFeature:
    id: int
    geom_type: str
    shp: object
    tags: Dict

def _make_valid(geom):
    # Robustify invalid polygons (handles self-intersections)
    try:
        return shapely.make_valid(geom)
    except Exception:
        try:
            return geom.buffer(0)
        except Exception:
            return geom

def osm_to_features(osm_json: Dict, transformer) -> List[OSMFeature]:
    nodes = {el["id"]:(el["lon"], el["lat"]) for el in osm_json.get("elements", []) if el["type"] == "node"}
    feats: List[OSMFeature] = []
    for el in osm_json.get("elements", []):
        if el.get("type") != "way":
            continue
        tags = el.get("tags", {})
        coords = [nodes.get(nid) for nid in el.get("nodes", []) if nodes.get(nid)]
        if not coords:
            continue
        if len(coords) >= 4 and coords[0] == coords[-1]:
            geom = {"type": "Polygon", "coordinates": [coords]}
            shp = _make_valid(transform(transformer, shape(geom)))
            feats.append(OSMFeature(el["id"], "Polygon", shp, tags))
        else:
            geom = {"type": "LineString", "coordinates": coords}
            shp = transform(transformer, shape(geom))
            feats.append(OSMFeature(el["id"], "LineString", shp, tags))
    logging.info("[step2] normalized features: %d (polys=%d, lines=%d)",
                 len(feats),
                 sum(1 for f in feats if f.geom_type == "Polygon"),
                 sum(1 for f in feats if f.geom_type == "LineString"))
    return feats

# ---------- Grid ----------
def build_grid(bbox: Tuple[float,float,float,float], cell_m: float = 1.5, max_cells: int = 8_000_000):
    s, w, n, e = bbox
    fwd = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
    minx, miny = transform(fwd, Point(w, s)).coords[0]
    maxx, maxy = transform(fwd, Point(e, n)).coords[0]
    W = int(math.ceil((maxx - minx) / cell_m))
    H = int(math.ceil((maxy - miny) / cell_m))
    cells = H * W
    if cells > max_cells:
        scale = math.sqrt(cells / max_cells)
        cell_m *= scale
        W = int(math.ceil((maxx - minx) / cell_m))
        H = int(math.ceil((maxy - miny) / cell_m))
        logging.warning("[step2] grid huge; bumped cell size to %.2fm", cell_m)
    origin = (minx, miny)
    logging.info("[step2] grid HxW = %dx%d (cell=%.2fm)", H, W, cell_m)
    return H, W, origin, cell_m

def _affine_from_origin(origin_xy: Tuple[float,float], H: int, cell: float):
    minx, miny = origin_xy
    maxy = miny + H * cell
    return (cell, 0.0, minx, 0.0, -cell, maxy)

# ---------- Rasterization helpers ----------
def rasterize_feats(H, W, origin, cell, feats: List[OSMFeature], cls: int, width_m: float = 0.0) -> np.ndarray:
    aff = _affine_from_origin(origin, H, cell)
    shapes = []
    for f in feats:
        if class_for(f.tags, f.geom_type) != cls:
            continue
        g = f.shp
        if isinstance(g, LineString) and width_m > 0:
            g = g.buffer(width_m / 2.0, cap_style=2)
        if not g.is_empty:
            shapes.append((g, 1))
    if not shapes:
        return np.zeros((H, W), dtype=np.uint8)
    # Later shapes overwrite earlier (replace) → matches our z-order.
    return rfeat.rasterize(
        shapes,
        out_shape=(H, W),
        transform=aff,
        fill=0,
        dtype=np.uint8,
        merge_alg=MergeAlg.replace,
    )

# ---------- Physics arrays ----------
def build_physics_arrays(H, W):
    semantic = np.zeros((H, W), dtype=np.uint8)
    walkable = np.zeros((H, W), dtype=np.uint8)
    cost     = np.full((H, W), 255, dtype=np.uint8)
    feature_id = np.full((H, W), -1, dtype=np.int32)
    return semantic, walkable, cost, feature_id

def set_walk_cost(semantic, walkable, cost):
    walkable[(semantic==SIDEWALK)|(semantic==FOOTPATH)|(semantic==PLAZA)|(semantic==CROSSING)|(semantic==PARKING)] = 1
    cost[semantic==SIDEWALK]  = 10
    cost[semantic==FOOTPATH]  = 12
    cost[semantic==PLAZA]     = 8
    cost[semantic==CROSSING]  = 12
    cost[semantic==PARKING]   = 18

def save_semantic_preview(semantic: np.ndarray, out_png: str):
    H, W = semantic.shape
    rgb = np.zeros((H, W, 3), dtype=np.uint8)
    for cls, color in PALETTE.items():
        rgb[semantic == cls] = color
    Image.fromarray(rgb).save(out_png)
    logging.info("[step2] wrote preview %s", out_png)

# ---------- Radius expansion ----------
def expand_bbox(lat: float, lon: float, radius_m: float) -> Tuple[float,float,float,float]:
    proj_wgs = pyproj.CRS("EPSG:4326")
    proj_merc = pyproj.CRS("EPSG:3857")
    fwd = pyproj.Transformer.from_crs(proj_wgs, proj_merc, always_xy=True).transform
    rev = pyproj.Transformer.from_crs(proj_merc, proj_wgs, always_xy=True).transform
    cx, cy = fwd(lon, lat)
    minx, miny = cx - radius_m, cy - radius_m
    maxx, maxy = cx + radius_m, cy + radius_m
    west, south = rev(minx, miny)
    east, north = rev(maxx, maxy)
    return (south, west, north, east)

# ---------- Orchestrator ----------
def run_step2_from_step1(step1: Dict, out_dir: str, cell_m: float = 1.5, radius_m: float | None = None) -> Dict:
    os.makedirs(out_dir, exist_ok=True)
    geo = step1["geocode"]

    if radius_m:
        bbox = expand_bbox(geo["lat"], geo["lon"], radius_m)
        logging.info("[step2] expanded bbox with radius_m=%.1f m → %s", radius_m, bbox)
    else:
        bbox = tuple(float(x) for x in geo["bbox"])
        logging.info("[step2] using original bbox → %s", bbox)

    # Grid
    H, W, origin, cell_m = build_grid(bbox, cell_m=cell_m)

    # Projection
    fwd = pyproj.Transformer.from_crs("EPSG:4326","EPSG:3857", always_xy=True).transform

    # Fetch + normalize
    osm = fetch_osm(bbox)
    feats = osm_to_features(osm, fwd)
    polys = [f for f in feats if f.geom_type == "Polygon"]
    lines = [f for f in feats if f.geom_type == "LineString"]

    # Arrays
    semantic, walkable, cost, feature_id = build_physics_arrays(H, W)

    # -------- SEMANTIC PASS (z-order) --------
    # Polygons first (base), then line buffers, then buildings last
    polygon_order = (WATER, GREEN, PARKING, PLAZA)   # base layers
    line_order    = ((SIDEWALK,2.5), (FOOTPATH,2.5), (CROSSING,4.0), (ROAD,6.0))
    final_layer   = (BUILDING,)                       # topmost

    # 1) polygons
    for cls in polygon_order:
        mask = rasterize_feats(H, W, origin, cell_m, polys, cls, width_m=0.0)
        semantic[mask == 1] = cls
        logging.info("[step2] painted class=%s (polys)", CLASS_NAMES[cls])

    # 2) lines (buffered)
    for cls, width in line_order:
        mask = rasterize_feats(H, W, origin, cell_m, lines, cls, width_m=width)
        semantic[mask == 1] = cls
        logging.info("[step2] painted class=%s (lines width=%.1fm)", CLASS_NAMES[cls], width)

    # 3) buildings last (override)
    bmask = rasterize_feats(H, W, origin, cell_m, polys, BUILDING, width_m=0.0)
    semantic[bmask == 1] = BUILDING
    logging.info("[step2] painted class=%s (override)", CLASS_NAMES[BUILDING])

    # -------- FEATURE-ID PASS (polygons only; same z-order) --------
    aff = _affine_from_origin(origin, H, cell_m)
    next_id = 1
    feature_rows: List[Dict] = []

    def _append_shapes(class_id: int, pool: List[OSMFeature], rows: List[Dict], start_id: int) -> Tuple[List[Tuple[object,int]], int]:
        shapes_vals: List[Tuple[object,int]] = []
        fid = start_id
        for f in pool:
            if class_for(f.tags, f.geom_type) != class_id:
                continue
            g = _make_valid(f.shp)
            if g.is_empty:
                continue
            shapes_vals.append((g, fid))
            row = {"feature_id": fid, "class": CLASS_NAMES[class_id], "tags": f.tags}
            if "name" in f.tags: row["name"] = f.tags["name"]
            rows.append(row)
            fid += 1
        return shapes_vals, fid

    # Build a composite draw list in the same z-order
    shapes_vals_all: List[Tuple[object,int]] = []
    for cls in polygon_order:
        sv, next_id = _append_shapes(cls, polys, feature_rows, next_id)
        shapes_vals_all.extend(sv)
    # buildings last
    sv, next_id = _append_shapes(BUILDING, polys, feature_rows, next_id)
    shapes_vals_all.extend(sv)

    if shapes_vals_all:
        fid_grid = rfeat.rasterize(
            shapes_vals_all,
            out_shape=(H, W),
            transform=aff,
            fill=0,
            dtype=np.int32,
            merge_alg=MergeAlg.replace,  # draw order respected
        )
        feature_id = fid_grid.astype(np.int32)
        feature_id[feature_id == 0] = -1
        logging.info("[step2] feature_id assigned for %d polygons", len(feature_rows))
    else:
        logging.warning("[step2] no polygon shapes for feature_id; grid remains -1")

    # Walkability & cost
    set_walk_cost(semantic, walkable, cost)

    # Save artifacts
    np.save(os.path.join(out_dir, "semantic.npy"), semantic)
    np.save(os.path.join(out_dir, "walkable.npy"), walkable)
    np.save(os.path.join(out_dir, "cost.npy"), cost)
    np.save(os.path.join(out_dir, "feature_id.npy"), feature_id)
    with open(os.path.join(out_dir, "feature_table.json"), "w", encoding="utf-8") as f:
        json.dump(feature_rows, f, indent=2)
    save_semantic_preview(semantic, os.path.join(out_dir, "semantic_preview.png"))

    # Summary
    unique, counts = np.unique(semantic, return_counts=True)
    mix = {CLASS_NAMES.get(int(k), str(int(k))): int(v) for k,v in zip(unique, counts)}
    logging.info("[step2] class mix: %s", mix)
    return {"H": H, "W": W, "cell_m": float(cell_m), "classes": mix, "out_dir": out_dir}

# --------------- Example ---------------
if __name__ == "__main__":
    # Minimal step-1 dict (just geocode)
    step1 = {
        "geocode": {
            "lat": 43.4765757,
            "lon": -80.5381896,
            "bbox": [43.4761396, -80.5389084, 43.4773694, -80.5377408]
        }
    }
    # 1 km radius neighborhood
    summary = run_step2_from_step1(step1, out_dir="out/society145_1km", cell_m=1.5, radius_m=1000)
    print(json.dumps(summary, indent=2))
