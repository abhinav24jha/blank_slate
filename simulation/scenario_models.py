#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Data models for environment scenarios and experiment configs.

A Scenario is a diff over baseline assets, primarily adding/updating POIs
near the target area. We support absolute grid positions (iy, ix) or
anchor-based placement using a named anchor (e.g., "center") with dx/dy
offsets in grid cells.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class POIAnchor(BaseModel):
    """Relative placement: start from an anchor and shift by dx/dy cells."""
    name: str = Field(description="Anchor name, e.g., 'center'")
    dx: int = 0
    dy: int = 0


class POIDef(BaseModel):
    """Definition of a POI to add to the grid.

    Either provide absolute grid coordinates (iy, ix), or an anchor with
    dx/dy offsets. Attributes can include pricing, quality, or open_hours.
    """
    type: str = Field(description="Category: cafe, grocery, pharmacy, restaurant, retail, education, health, transit, other")
    name: Optional[str] = None
    iy: Optional[int] = None
    ix: Optional[int] = None
    anchor: Optional[POIAnchor] = None
    attrs: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_position(self) -> "POIDef":
        if (self.iy is None or self.ix is None) and self.anchor is None:
            raise ValueError("POIDef requires either (iy, ix) or anchor")
        return self


class POIUpdate(BaseModel):
    """Mutate matching POIs by id/name/type and set attributes."""
    match: Dict[str, Any]
    set: Dict[str, Any]


class Scenario(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    poi_add: List[POIDef] = Field(default_factory=list)
    poi_update: List[POIUpdate] = Field(default_factory=list)
    tags: Dict[str, Any] = Field(default_factory=dict)


class NeedBias(BaseModel):
    category: str
    weight: float = Field(ge=0.0, le=1.0)


class ExperimentConfig(BaseModel):
    seed: int = 12345
    duration_s: float = 180.0
    agent_count: int = 50
    speed: float = 1.0
    baseline_dir: str = "out/society145_1km"
    exp_out_dir: str = "simulation/out/experiments"


__all__ = [
    "POIAnchor",
    "POIDef",
    "POIUpdate",
    "Scenario",
    "NeedBias",
    "ExperimentConfig",
]


