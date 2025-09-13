#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Steps 0–1 (lean):
- Step 0: accept multiple hypotheses as a tuple
- Step 1: geocode from a provided structured location dict:
    {"site":..., "city":..., "region":..., "country":...}
No free-text extraction. Loud logs, safe fallbacks.
"""

from __future__ import annotations
import json, math, time, logging
from dataclasses import dataclass
from typing import Tuple, Iterable, Union, Optional, Dict, List
import requests

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
UA = {"User-Agent": "agent-sim-geo/0.4 (debuggable; contact: dev@example.com)"}
NOMINATIM = "https://nominatim.openstreetmap.org/search"

# ---------------- Step 0: Hypotheses tuple ----------------
@dataclass(frozen=True)
class ProjectSpec:
    question: str
    user_answer: str
    hypotheses: Tuple[str, ...]  # multiple hypotheses

def _normalize_hypotheses(h: Union[str, Iterable[str]]) -> Tuple[str, ...]:
    if isinstance(h, str):
        items = [h]
    else:
        items = list(h)
    out: List[str] = []
    seen = set()
    for x in items:
        x2 = (x or "").strip()
        if x2 and x2 not in seen:
            seen.add(x2)
            out.append(x2)
    return tuple(out)

def make_project_spec(question: str, user_answer: str, hypotheses: Union[str, Iterable[str]]) -> ProjectSpec:
    hyp = _normalize_hypotheses(hypotheses)
    logging.info("[step0] %d hypothesis(es)", len(hyp))
    return ProjectSpec(question=question, user_answer=user_answer, hypotheses=hyp)

# ---------------- Step 1: Geocode from structured location ----------------
@dataclass(frozen=True)
class GeoContext:
    query_used: str
    display_name: str
    lat: float
    lon: float
    bbox: Tuple[float, float, float, float]  # (south, west, north, east)
    source: str = "nominatim"

def _bbox_from_point(lat: float, lon: float, size_m: float = 450.0) -> Tuple[float, float, float, float]:
    """Square bbox half-width size_m meters."""
    dlat = size_m / 111_320.0
    dlon = size_m / (111_320.0 * max(0.1, math.cos(math.radians(lat))))
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)

def _join_nonempty(parts: Iterable[Optional[str]]) -> str:
    return ", ".join([p.strip() for p in parts if p and p.strip()])

def geocode_structured_location(
    location: Dict[str, Optional[str]],
    *,
    size_m_if_no_bbox: float = 450.0,
    timeout: int = 20
) -> GeoContext:
    """
    location = {"site":..., "city":..., "region":..., "country":...}
    Try 'site, city, region, country' first (if site present),
    then 'city, region, country'.
    """
    site   = (location.get("site") or "").strip()
    city   = (location.get("city") or "").strip()
    region = (location.get("region") or "").strip()
    country= (location.get("country") or "").strip()

    candidates = []
    if site:
        candidates.append(_join_nonempty([site, city, region, country]))
    candidates.append(_join_nonempty([city, region, country]))

    last_error = None
    for q in candidates:
        if not q:
            continue
        try:
            logging.info("[step1] geocode try: '%s'", q)
            r = requests.get(
                NOMINATIM,
                params={"q": q, "format": "jsonv2", "limit": 1, "addressdetails": 1},
                headers=UA,
                timeout=timeout,
            )
            r.raise_for_status()
            js = r.json()
            if not js:
                logging.warning("[step1] EMPTY geocode for '%s'", q)
                last_error = "empty"
                continue
            hit = js[0]
            lat, lon = float(hit["lat"]), float(hit["lon"])
            bb = hit.get("boundingbox")
            if bb and len(bb) == 4:
                south, north, west, east = map(float, bb)
                bbox = (south, west, north, east)
                logging.info("[step1] OK '%s' -> lat=%.6f lon=%.6f (bbox from provider)", q, lat, lon)
            else:
                bbox = _bbox_from_point(lat, lon, size_m=size_m_if_no_bbox)
                logging.info("[step1] OK '%s' -> lat=%.6f lon=%.6f (synth bbox ±%.0fm)", q, lat, lon, size_m_if_no_bbox)
            return GeoContext(
                query_used=q,
                display_name=hit.get("display_name", q),
                lat=lat, lon=lon, bbox=bbox
            )
        except Exception as e:
            logging.exception("[step1] ERROR for '%s': %s", q, e)
            last_error = str(e)
        time.sleep(0.5)  # be nice to Nominatim

    raise RuntimeError(f"Geocoding failed for all candidates. last_error={last_error}")

# ---------------- Example main ----------------
if __name__ == "__main__":
    # Step 0 inputs
    question = "What area needs improvement and what problems do you see?"
    user_answer = (
        "The area around the building has nothing but parking in front. "
        "People walk far for groceries; the space lacks local amenities."
    )
    hypotheses = (
        "Add a compact grocery at the frontage",
        "Build a small clubhouse with sheltered seating",
        "Convert two bays to food kiosks (micro food hall)"
    )
    spec = make_project_spec(question, user_answer, hypotheses)

    # Provided structured location (no extraction)
    location = {
        "site": "Society 145",
        "city": "Waterloo",
        "region": "Ontario",
        "country": "Canada",
    }

    # Step 1: geocode from structured location
    geo = geocode_structured_location(location, size_m_if_no_bbox=450.0)
    logging.info("[step1] GeoContext: %s", geo)

    # Pretty output to eyeball
    print(json.dumps({
        "project": {"question": spec.question, "hypotheses": list(spec.hypotheses)},
        "location_input": location,
        "geocode": {
            "query_used": geo.query_used,
            "display_name": geo.display_name,
            "lat": geo.lat,
            "lon": geo.lon,
            "bbox": geo.bbox,
        }
    }, indent=2))
