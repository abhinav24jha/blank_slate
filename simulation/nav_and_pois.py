#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 3 — POIs + Nav (A*) for agent-ready world  [ENTERABLE BUILDINGS + FLEX SPAWNS]

Adds:
- Buildings with snapped POIs become *enterable*:
    * interior cells set walkable with moderate cost
    * a "doorway" path carved to nearest outdoor walkable cell
- Flexible spawn selection:
    * spawn_mode="random_all"  -> random from all walkable
    * spawn_mode="cluster"     -> cluster around provided lon/lat OR (iy,ix)
- Labels:
    * labels.json combining named POIs and named features from Step 2 (feature_table.json)
- Venues:
    * venues.json grouping commercial POIs into plaza/venue polygons (grid coords)
"""

from __future__ import annotations
import os, json, math, logging, random
from typing import Dict, List, Tuple, Optional
import numpy as np
from dataclasses import dataclass
from PIL import Image, ImageDraw

import requests
import pyproj
from shapely.geometry import Point, MultiPoint, Polygon
from shapely.ops import transform
from heapq import heappush, heappop

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

UA = {"User-Agent": "agent-sim-step3/0.7 (labels+venues)"}
OVERPASS = "https://overpass-api.de/api/interpreter"

# ---------- Categories ----------
GROCERY_KEYS = {
    ("shop", "supermarket"), ("shop", "convenience"), ("shop", "greengrocer"),
    ("shop", "butcher"), ("shop", "bakery"), ("amenity", "marketplace")
}
PHARMACY_KEYS = {("amenity","pharmacy"), ("shop","pharmacy")}
CAFE_KEYS     = {("amenity","cafe"), ("amenity","fast_food"), ("amenity","coffee_shop")}
RESTAURANT_KEYS = {("amenity","restaurant"), ("amenity","food_court")}
TRANSIT_KEYS  = {("highway","bus_stop"), ("public_transport","platform"), ("railway","station")}
EDU_KEYS      = {("amenity","school"), ("amenity","university"), ("amenity","college")}
HEALTH_KEYS   = {("amenity","clinic"), ("amenity","hospital"), ("amenity","doctors")}
RETAIL_KEYS   = {("shop","mall"), ("shop","department_store")}

# Semantic classes (match Step 2)
VOID, BUILDING, SIDEWALK, FOOTPATH, PARKING, PLAZA, GREEN, WATER, ROAD, CROSSING = range(10)

PALETTE = {
    0:(240,240,240), 1:(60,60,60), 2:(230,230,230), 3:(200,200,200),
    4:(210,210,160), 5:(235,215,160), 6:(140,190,140), 7:(150,180,220),
    8:(120,120,120), 9:(250,250,120)
}

# ---------- Utilities ----------
def expand_bbox(lat: float, lon: float, radius_m: float) -> Tuple[float,float,float,float]:
    proj_wgs = pyproj.CRS("EPSG:4326"); proj_merc = pyproj.CRS("EPSG:3857")
    fwd = pyproj.Transformer.from_crs(proj_wgs, proj_merc, always_xy=True).transform
    rev = pyproj.Transformer.from_crs(proj_merc, proj_wgs, always_xy=True).transform
    cx, cy = fwd(lon, lat)
    minx, miny = cx - radius_m, cy - radius_m
    maxx, maxy = cx + radius_m, cy + radius_m
    west, south = rev(minx, miny); east, north = rev(maxx, maxy)
    return (south, west, north, east)

def fetch_amenity_nodes_and_ways(bbox: Tuple[float,float,float,float]) -> Dict:
    """Fetch both nodes and ways with amenity/shop/public_transport (+center for ways)."""
    s, w, n, e = bbox
    query = f"""
    [out:json][timeout:60];
    (
      node["amenity"]({s},{w},{n},{e});
      node["shop"]({s},{w},{n},{e});
      node["public_transport"]({s},{w},{n},{e});
      node["highway"="bus_stop"]({s},{w},{n},{e});
      way["amenity"]({s},{w},{n},{e});
      way["shop"]({s},{w},{n},{e});
      way["public_transport"]({s},{w},{n},{e});
    );
    out body center;
    """
    logging.info("[step3] Overpass (POI nodes+ways) fetch bbox=%s", bbox)
    r = requests.post(OVERPASS, data=query, headers=UA, timeout=90)
    r.raise_for_status()
    js = r.json()
    logging.info("[step3] POI elements: %d", len(js.get("elements", [])))
    return js

def classify_poi(tags: Dict) -> Optional[str]:
    kv = {(k,v) for k,v in tags.items()}
    if kv & GROCERY_KEYS: return "grocery"
    if kv & PHARMACY_KEYS: return "pharmacy"
    if kv & CAFE_KEYS: return "cafe"
    if kv & RESTAURANT_KEYS: return "restaurant"
    if kv & TRANSIT_KEYS: return "transit"
    if kv & EDU_KEYS: return "education"
    if kv & HEALTH_KEYS: return "health"
    if kv & RETAIL_KEYS: return "retail"
    
    # Broader fallbacks for shops
    shop_type = tags.get("shop")
    if shop_type in ("alcohol","general","variety","convenience","supermarket"): return "grocery"
    if shop_type in ("clothes","shoes","jewelry","electronics","books","furniture"): return "retail"
    if shop_type in ("hairdresser","beauty","optician"): return "health"
    
    # Amenities
    amenity = tags.get("amenity")
    if amenity in ("bank","atm","post_office"): return "retail"
    if amenity in ("library","community_centre","place_of_worship"): return "education"
    if amenity in ("fuel","car_wash","parking"): return "transit"
    
    # If it has a name, it's probably worth showing
    if tags.get("name"): return "other"
    
    return None

def is_commercial_poi(tags: Dict, ptype: Optional[str]) -> bool:
    if not tags: tags = {}
    if ptype in ("grocery","pharmacy","cafe","restaurant","retail","education","health"): return True
    if tags.get("shop") or tags.get("amenity") in ("restaurant","cafe","fast_food","pharmacy","bank","library","clinic","hospital","school","university","college"): return True
    return False

def cluster_commercial_pois(pois: List[Dict], *, cell_eps: int = 10, min_pts: int = 3) -> List[List[Dict]]:
    # Simple grid-based DBSCAN: group points within cell_eps in grid units
    pts = [(p.get("snapped") or {"iy":p["iy"],"ix":p["ix"]}) for p in pois]
    used = [False]*len(pts)
    clusters: List[List[Dict]] = []
    for i, p in enumerate(pts):
        if used[i]: continue
        neigh = [i]
        for j, q in enumerate(pts):
            if i==j or used[j]:
                continue
            if abs(p["iy"]-q["iy"]) <= cell_eps and abs(p["ix"]-q["ix"]) <= cell_eps:
                neigh.append(j)
        if len(neigh) >= min_pts:
            for j in neigh: used[j]=True
            clusters.append([pois[j] for j in neigh])
    return clusters

def build_venue_polygon(cluster: List[Dict]) -> Optional[Dict]:
    # Return a dict {polygon:[[iy,ix],...], name:str, poi_ids:[...]} in grid coords
    pts = [( (p.get("snapped") or p)["ix"], (p.get("snapped") or p)["iy"] ) for p in cluster]
    mp = MultiPoint([Point(x,y) for x,y in pts])
    # Buffer ~6 cells then shrink a bit for a smooth outline
    poly: Polygon = mp.buffer(6).buffer(-2)
    if poly.is_empty:
        poly = mp.buffer(5)
    if poly.is_empty:
        return None
    coords = list(poly.exterior.coords)
    # Name heuristics: majority POI name prefix or nearest named feature via cluster
    names = [p.get("name") for p in cluster if p.get("name")]
    name = None
    if names:
        # pick the longest common-ish string
        names.sort(key=lambda s: (-len(s), s))
        name = names[0]
    return {
        "name": name or "Venue",
        "type": "plaza_venue",
        "polygon": [[int(y), int(x)] for x,y in coords],
        "poi_ids": [i for i,_ in enumerate(cluster)]
    }

# ---------- Grid <-> world transforms ----------
@dataclass
class GeoGrid:
    origin_minx: float
    origin_miny: float
    H: int
    W: int
    cell_m: float
    proj_fwd: object   # lon/lat -> meters
    proj_rev: object   # meters  -> lon/lat

    def lonlat_to_ij(self, lon: float, lat: float) -> Optional[Tuple[int,int]]:
        x, y = self.proj_fwd(lon, lat)
        ix = int((x - self.origin_minx) // self.cell_m)
        iy = int((y - self.origin_miny) // self.cell_m)
        if 0 <= ix < self.W and 0 <= iy < self.H: return (iy, ix)
        return None

    def ij_to_lonlat(self, iy: int, ix: int) -> Tuple[float,float]:
        x = self.origin_minx + (ix + 0.5)*self.cell_m
        y = self.origin_miny + (iy + 0.5)*self.cell_m
        lon, lat = self.proj_rev(x, y)
        return lon, lat

# ---------- A* ----------
NEI8 = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
DIAG = 1.41421356237

def astar(cost: np.ndarray, walkable: np.ndarray, start: Tuple[int,int], goal: Tuple[int,int]) -> Optional[List[Tuple[int,int]]]:
    H, W = cost.shape
    (sy, sx), (gy, gx) = start, goal
    if not (0<=sx<W and 0<=sy<H and 0<=gx<W and 0<=gy<H):
        logging.warning("[step3][A*] start/goal OOB: start=%s goal=%s", start, goal); return None
    if walkable[sy, sx] == 0 or walkable[gy, gx] == 0:
        logging.warning("[step3][A*] start or goal not walkable: start=%s goal=%s", start, goal); return None

    gscore = np.full((H,W), np.inf, dtype=np.float32)
    py = np.full((H,W), -1, dtype=np.int32); px = np.full((H,W), -1, dtype=np.int32)
    gscore[sy, sx] = 0.0

    def h(y,x):
        dy, dx = abs(y-gy), abs(x-gx)
        return (max(dy,dx) + (DIAG-1.0)*min(dy,dx))

    openq = []
    heappush(openq, (h(sy,sx), 0.0, sy, sx))

    while openq:
        f, g, y, x = heappop(openq)
        if (y,x) == (gy,gx):
            path = [(y,x)]
            while (y,x) != (sy,sx):
                y, x = int(py[y,x]), int(px[y,x])
                path.append((y,x))
            return list(reversed(path))
        for dy,dx in NEI8:
            ny, nx = y+dy, x+dx
            if not (0<=nx<W and 0<=ny<H): continue
            if walkable[ny,nx] == 0: continue
            step = DIAG if dy and dx else 1.0
            ng = gscore[y,x] + step * float(cost[ny,nx])
            if ng < gscore[ny,nx]:
                gscore[ny,nx] = ng
                py[ny,nx] = y; px[ny,nx] = x
                heappush(openq, (ng + h(ny,nx), ng, ny, nx))
    logging.warning("[step3][A*] no path found"); return None

# ---------- Neighborhood searches ----------
def nearest_walkable(walkable: np.ndarray, seed_y: int, seed_x: int, max_r: int = 600, stride: int = 3) -> Optional[Tuple[int,int]]:
    H, W = walkable.shape
    for r in range(0, max_r, stride):
        y0, y1 = max(0, seed_y-r), min(H-1, seed_y+r)
        x0, x1 = max(0, seed_x-r), min(W-1, seed_x+r)
        sub = np.argwhere(walkable[y0:y1+1, x0:x1+1] == 1)
        if sub.size:
            vy, vx = sub[0]; return (y0+int(vy), x0+int(vx))
    return None

def snap_to_walkable(walkable: np.ndarray, iy: int, ix: int, max_r: int = 20) -> Optional[Tuple[int,int]]:
    H, W = walkable.shape
    if 0 <= ix < W and 0 <= iy < H and walkable[iy, ix] == 1: return (iy, ix)
    for r in range(1, max_r+1):
        y0, y1 = max(0, iy-r), min(H-1, iy+r)
        x0, x1 = max(0, ix-r), min(W-1, ix+r)
        sub = np.argwhere(walkable[y0:y1+1, x0:x1+1] == 1)
        if sub.size:
            vy, vx = sub[0]; return (y0+int(vy), x0+int(vx))
    return None

# ---------- Door carving ----------
def carve_doorway(walkable: np.ndarray, cost: np.ndarray, src: Tuple[int,int], dst: Tuple[int,int], width: int = 2, step_cost: int = 10):
    """
    Carve a thin walkable corridor from src (inside building) to dst (nearest outdoor walkable).
    Uses straight-line Bresenham; keeps it simple & fast.
    """
    def bresenham(y0,x0,y1,x1):
        points = []
        dx = abs(x1-x0); sx = 1 if x0 < x1 else -1
        dy = -abs(y1-y0); sy = 1 if y0 < y1 else -1
        err = dx + dy
        y, x = y0, x0
        while True:
            points.append((y,x))
            if x==x1 and y==y1: break
            e2 = 2*err
            if e2 >= dy: err += dy; x += sx
            if e2 <= dx: err += dx; y += sy
        return points

    H, W = walkable.shape
    y0,x0 = src; y1,x1 = dst
    for (y,x) in bresenham(y0,x0,y1,x1):
        if 0<=x<W and 0<=y<H:
            walkable[y,x] = 1
            cost[y,x] = step_cost
            # widen corridor
            for oy in range(-width//2, width//2+1):
                for ox in range(-width//2, width//2+1):
                    yy, xx = y+oy, x+ox
                    if 0<=xx<W and 0<=yy<H:
                        walkable[yy,xx] = 1
                        cost[yy,xx] = step_cost

# ---------- Spawns ----------
def sample_spawns(walkable: np.ndarray, *, n: int, spawn_mode: str = "random_all",
                  grid: Optional[GeoGrid] = None, center_lonlat: Optional[Tuple[float,float]] = None,
                  center_ij: Optional[Tuple[int,int]] = None, jitter_sigma_m: float = 60.0) -> List[Tuple[int,int]]:
    H, W = walkable.shape
    coords: List[Tuple[int,int]] = []
    if spawn_mode == "random_all":
        ys, xs = np.where(walkable == 1)
        if ys.size == 0: return coords
        idx = np.random.choice(ys.size, size=min(n, ys.size), replace=False)
        coords = [(int(ys[i]), int(xs[i])) for i in idx]
        logging.info("[step3] spawns=random_all -> %d", len(coords))
        return coords

    if spawn_mode == "cluster":
        if center_ij is None and (center_lonlat is None or grid is None):
            raise ValueError("cluster mode requires center_ij OR (center_lonlat + grid)")
        if center_ij is None:
            ij = grid.lonlat_to_ij(center_lonlat[0], center_lonlat[1])  # lon,lat
            if ij is None: raise ValueError("center_lonlat projects outside grid")
            center_ij = ij
        cy, cx = center_ij
        # gaussian jitter in meters → pixels
        sigma_px = max(1.0, jitter_sigma_m / grid.cell_m) if grid else 40.0
        for _ in range(n*5):  # attempt pool
            jy = int(round(np.random.normal(cy, sigma_px)))
            jx = int(round(np.random.normal(cx, sigma_px)))
            if 0 <= jx < W and 0 <= jy < H and walkable[jy, jx] == 1:
                coords.append((jy, jx))
                if len(coords) >= n: break
        logging.info("[step3] spawns=cluster -> %d (requested %d)", len(coords), n)
        return coords

    raise ValueError(f"unknown spawn_mode={spawn_mode}")

# ---------- Main API ----------
def run_step3_prepare_nav_and_pois(
    step1: Dict,
    out_dir: str,
    *,
    cell_m: float,
    radius_m: float,
    make_buildings_enterable: bool = True,
    doorway_search_px: int = 60,
    doorway_width: int = 2,
    interior_cost: int = 12,
    spawn_mode: str = "random_all",
    spawn_center_lonlat: Optional[Tuple[float,float]] = None,
    spawn_center_ij: Optional[Tuple[int,int]] = None,
    n_spawns: int = 50
) -> Dict:

    # Load grids from Step 2
    semantic = np.load(os.path.join(out_dir, "semantic.npy"))
    walkable = np.load(os.path.join(out_dir, "walkable.npy"))
    cost     = np.load(os.path.join(out_dir, "cost.npy"))
    feature_id = np.load(os.path.join(out_dir, "feature_id.npy"))
    H, W = semantic.shape
    logging.info("[step3] loaded grids HxW=%dx%d", H, W)

    # Bbox & grid geometry
    lat, lon = float(step1["geocode"]["lat"]), float(step1["geocode"]["lon"])
    bbox = expand_bbox(lat, lon, radius_m)
    logging.info("[step3] bbox (radius_m=%.0f): %s", radius_m, bbox)

    proj_wgs = pyproj.CRS("EPSG:4326"); proj_merc = pyproj.CRS("EPSG:3857")
    fwd = pyproj.Transformer.from_crs(proj_wgs, proj_merc, always_xy=True).transform
    rev = pyproj.Transformer.from_crs(proj_merc, proj_wgs, always_xy=True).transform
    s, w, n, e = bbox
    minx, miny = transform(fwd, Point(w, s)).coords[0]
    origin_minx, origin_miny = float(minx), float(miny)
    grid = GeoGrid(origin_minx, origin_miny, H, W, cell_m, fwd, rev)

    # Fetch & classify POIs (nodes + ways)
    raw = fetch_amenity_nodes_and_ways(bbox)
    classified = []
    for el in raw.get("elements", []):
      try:
        tags = el.get("tags", {})
        ptype = classify_poi(tags)
        if not ptype: continue
        if el.get("type") == "node":
            lon_p, lat_p = float(el["lon"]), float(el["lat"])
        elif el.get("type") == "way" and "center" in el:
            lon_p, lat_p = float(el["center"]["lon"]), float(el["center"]["lat"])
        else:
            continue
        ij = grid.lonlat_to_ij(lon_p, lat_p)
        if ij is None: continue
        iy, ix = ij
        classified.append({
            "type": ptype, "iy": int(iy), "ix": int(ix),
            "lon": lon_p, "lat": lat_p, "name": tags.get("name"), "tags": tags
        })
      except Exception as ex:
        logging.debug("[step3] skip el due to %s", ex)
    logging.info("[step3] classified POIs kept: %d", len(classified))

    # Snap to walkable
    snapped, failures = [], 0
    for p in classified:
        snap = snap_to_walkable(walkable, p["iy"], p["ix"], max_r=20)
        if snap is None:
            failures += 1; p["snapped"] = None
        else:
            sy, sx = snap; p["snapped"] = {"iy": int(sy), "ix": int(sx)}
        snapped.append(p)
    logging.info("[step3] snapped POIs: %d, failed: %d", len(snapped)-failures, failures)

    # ---- Enterable buildings (unchanged core) ----
    if make_buildings_enterable:
        open_fids = set()
        for p in snapped:
            iy0, ix0 = p["iy"], p["ix"]
            if 0 <= ix0 < W and 0 <= iy0 < H:
                if semantic[iy0, ix0] == BUILDING and feature_id[iy0, ix0] > 0:
                    open_fids.add(int(feature_id[iy0, ix0]))
        logging.info("[step3] enterable buildings count (via POIs inside): %d", len(open_fids))
        for fid in open_fids:
            interior = (feature_id == fid)
            if not np.any(interior): continue
            walkable[interior] = 1
            cost[interior] = interior_cost
            ys, xs = np.where(interior)
            cy, cx = int(np.mean(ys)), int(np.mean(xs))
            best = None; best_d2 = 1e18
            y0, x0 = max(0, cy-doorway_search_px), max(0, cx-doorway_search_px)
            y1, x1 = min(H-1, cy+doorway_search_px), min(W-1, cx+doorway_search_px)
            for y in range(y0, y1+1, 2):
                for x in range(x0, x1+1, 2):
                    if walkable[y,x] == 1 and not interior[y,x]:
                        d2 = (y-cy)*(y-cy)+(x-cx)*(x-cx)
                        if d2 < best_d2:
                            best_d2 = d2; best = (y,x)
            if best:
                carve_doorway(walkable, cost, (cy,cx), best, width=doorway_width, step_cost=10)

    # Save POIs (with snapped info)
    with open(os.path.join(out_dir, "pois.json"), "w", encoding="utf-8") as f:
        json.dump(snapped, f, indent=2)

    # Save navgraph components
    np.savez_compressed(
        os.path.join(out_dir, "navgraph.npz"),
        walkable=walkable.astype(np.uint8),
        cost=cost.astype(np.uint8),
        origin=np.array([origin_minx, origin_miny], dtype=np.float64),
        cell_m=np.array([cell_m], dtype=np.float32),
    )
    logging.info("[step3] wrote navgraph.npz and pois.json")

    # ---- Labels from features + POIs ----
    labels: List[Dict] = []
    
    # 1) Named features (from Step 2)
    ft_path = os.path.join(out_dir, "feature_table.json")
    logging.info("[step3] checking feature_table at %s", ft_path)
    if os.path.exists(ft_path):
        try:
            with open(ft_path, "r", encoding="utf-8") as f:
                table = json.load(f)
            logging.info("[step3] loaded feature_table with %d entries", len(table))
            # Create centroid from raster for each named feature
            feature_labels = 0
            for row in table:
                name = row.get("name") or (row.get("tags") or {}).get("name")
                fid = int(row.get("feature_id", -1))
                if not name or fid <= 0: continue
                mask = (feature_id == fid)
                if not np.any(mask): continue
                ys, xs = np.where(mask)
                cy, cx = int(np.mean(ys)), int(np.mean(xs))
                labels.append({"text": name, "iy": int(cy), "ix": int(cx), "source": "feature", "class": row.get("class")})
                feature_labels += 1
            logging.info("[step3] added %d feature labels", feature_labels)
        except Exception as e:
            logging.warning("[step3] feature_table labels failed: %s", e)
    else:
        logging.warning("[step3] no feature_table.json found at %s", ft_path)

    # 2) Named POIs
    poi_labels = 0
    for p in snapped:
        nm = p.get("name") or (p.get("tags") or {}).get("name")
        loc = p.get("snapped") or {"iy": p["iy"], "ix": p["ix"]}
        if nm and loc:
            labels.append({"text": nm, "iy": int(loc["iy"]), "ix": int(loc["ix"]), "source": "poi", "type": p.get("type")})
            poi_labels += 1
    logging.info("[step3] added %d POI labels", poi_labels)

    # ---- Venues from commercial POI clusters ----
    commercial = [p for p in snapped if is_commercial_poi(p.get("tags", {}), p.get("type"))]
    clusters = cluster_commercial_pois(commercial, cell_eps=12, min_pts=4)
    venues: List[Dict] = []
    for cl in clusters:
        v = build_venue_polygon(cl)
        if v: venues.append(v)
    with open(os.path.join(out_dir, "venues.json"), "w", encoding="utf-8") as f:
        json.dump(venues, f, indent=2)
    logging.info("[step3] wrote venues.json (count=%d)", len(venues))

    # Write labels file
    labels_path = os.path.join(out_dir, "labels.json")
    try:
        with open(labels_path, "w", encoding="utf-8") as f:
            json.dump(labels, f, indent=2)
        logging.info("[step3] wrote labels.json to %s (count=%d)", labels_path, len(labels))
    except Exception as e:
        logging.error("[step3] failed to write labels.json: %s", e)

    # Debug overlays (unchanged)
    rgb = np.zeros((H, W, 3), dtype=np.uint8)
    for cls, color in PALETTE.items(): rgb[semantic == cls] = color
    ov = Image.fromarray(rgb)
    draw = ImageDraw.Draw(ov)
    for p in snapped:
        if p["snapped"]: x, y = p["snapped"]["ix"], p["snapped"]["iy"]; draw.ellipse((x-2,y-2,x+2,y+2), fill=(0,255,0))
        else:            x, y = p["ix"], p["iy"];                   draw.ellipse((x-2,y-2,x+2,y+2), fill=(255,0,0))
    ov.save(os.path.join(out_dir, "poi_overlay.png"))
    logging.info("[step3] wrote poi_overlay.png (green=snapped, red=unsnapped)")

    # Demo route (unchanged shortened)
    demo_path = None
    return {
        "pois_total": len(snapped),
        "demo_routed": bool(demo_path),
        "spawns": 0,
        "out_dir": out_dir,
        "labels": len(labels),
        "venues": len(venues)
    }

if __name__ == "__main__":
    step1 = {"geocode": {"lat": 43.4765757, "lon": -80.5381896}}
    OUT = "out/society145_1km"; CELL_M = 1.5; RADIUS_M = 1000
    summary = run_step3_prepare_nav_and_pois(step1, out_dir=OUT, cell_m=CELL_M, radius_m=RADIUS_M)
    print(json.dumps(summary, indent=2))
