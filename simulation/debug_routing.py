#!/usr/bin/env python3
"""
Debug script to understand why A* routing is failing
"""

import numpy as np
import json
from PIL import Image, ImageDraw
import os

def analyze_connectivity(walkable, start, goal):
    """Analyze connectivity between start and goal using flood fill"""
    H, W = walkable.shape
    sy, sx = start
    gy, gx = goal
    
    print(f"Start: {start}, Goal: {goal}")
    print(f"Start walkable: {walkable[sy, sx]}")
    print(f"Goal walkable: {walkable[gy, gx]}")
    
    # Flood fill from start
    visited = np.zeros_like(walkable, dtype=bool)
    queue = [(sy, sx)]
    visited[sy, sx] = True
    reachable_count = 0
    
    directions = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
    
    while queue:
        y, x = queue.pop(0)
        reachable_count += 1
        
        for dy, dx in directions:
            ny, nx = y + dy, x + dx
            if (0 <= ny < H and 0 <= nx < W and 
                not visited[ny, nx] and walkable[ny, nx] == 1):
                visited[ny, nx] = True
                queue.append((ny, nx))
    
    goal_reachable = visited[gy, gx]
    print(f"Goal reachable from start: {goal_reachable}")
    print(f"Total reachable cells from start: {reachable_count}")
    print(f"Total walkable cells: {np.sum(walkable)}")
    
    return goal_reachable, visited

def visualize_connectivity(walkable, visited, start, goal, output_path):
    """Create visualization of connectivity"""
    H, W = walkable.shape
    
    # Create RGB image
    rgb = np.zeros((H, W, 3), dtype=np.uint8)
    
    # Gray for non-walkable
    rgb[walkable == 0] = (128, 128, 128)
    
    # White for walkable but unreachable
    mask = (walkable == 1) & (~visited)
    rgb[mask] = (255, 255, 255)
    
    # Green for reachable
    rgb[visited] = (0, 255, 0)
    
    img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(img)
    
    # Mark start and goal
    sy, sx = start
    gy, gx = goal
    
    # Start in red
    draw.ellipse((sx-5, sy-5, sx+5, sy+5), fill=(255, 0, 0))
    # Goal in blue  
    draw.ellipse((gx-5, gy-5, gx+5, gy+5), fill=(0, 0, 255))
    
    img.save(output_path)
    print(f"Saved connectivity visualization to {output_path}")

def analyze_local_area(walkable, cost, pos, radius=10):
    """Analyze walkability in local area around a position"""
    H, W = walkable.shape
    y, x = pos
    
    y0 = max(0, y - radius)
    y1 = min(H, y + radius + 1)
    x0 = max(0, x - radius)
    x1 = min(W, x + radius + 1)
    
    local_walkable = walkable[y0:y1, x0:x1]
    local_cost = cost[y0:y1, x0:x1]
    
    print(f"\nLocal area around {pos} (radius {radius}):")
    print(f"Walkable cells: {np.sum(local_walkable)}/{local_walkable.size}")
    print(f"Cost range: {np.min(local_cost[local_walkable==1])} - {np.max(local_cost[local_walkable==1])}")
    
    # Show pattern
    print("Walkability pattern (1=walkable, 0=blocked):")
    for row in local_walkable:
        print(''.join(['1' if x else '0' for x in row]))

if __name__ == "__main__":
    out_dir = "out/society145_1km"
    
    # Load navigation data
    nav_data = np.load(os.path.join(out_dir, "navgraph.npz"))
    walkable = nav_data['walkable']
    cost = nav_data['cost']
    
    # Load POIs to find a grocery goal
    with open(os.path.join(out_dir, "pois.json"), 'r') as f:
        pois = json.load(f)
    
    # Find a snapped grocery
    groceries = [p for p in pois if p["type"] == "grocery" and p.get("snapped")]
    print(f"Found {len(groceries)} snapped groceries")
    
    if groceries:
        # Use the demo positions from the log
        start = (150, 283)
        goal = (130, 129)
        
        print("=== CONNECTIVITY ANALYSIS ===")
        goal_reachable, visited = analyze_connectivity(walkable, start, goal)
        
        print("\n=== LOCAL ANALYSIS - START ===")
        analyze_local_area(walkable, cost, start, radius=15)
        
        print("\n=== LOCAL ANALYSIS - GOAL ===") 
        analyze_local_area(walkable, cost, goal, radius=15)
        
        # Create visualization
        visualize_connectivity(walkable, visited, start, goal, 
                             os.path.join(out_dir, "connectivity_debug.png"))
        
        # Additional stats
        print(f"\n=== OVERALL STATS ===")
        print(f"Grid size: {walkable.shape}")
        print(f"Total walkable: {np.sum(walkable)} / {walkable.size}")
        print(f"Walkable percentage: {100 * np.sum(walkable) / walkable.size:.2f}%")
        
        # Check for isolated regions
        unique_costs = np.unique(cost[walkable == 1])
        print(f"Cost values in walkable areas: {unique_costs}")
        
    else:
        print("No snapped groceries found for analysis")
