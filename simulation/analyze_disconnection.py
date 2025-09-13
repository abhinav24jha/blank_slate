#!/usr/bin/env python3
"""
Analyze what's causing the disconnection in the walkable areas
"""

import numpy as np
import json
from PIL import Image, ImageDraw
import os

# Semantic classes (match Step 2)
VOID, BUILDING, SIDEWALK, FOOTPATH, PARKING, PLAZA, GREEN, WATER, ROAD, CROSSING = range(10)
CLASS_NAMES = {
    VOID:"void", BUILDING:"building", SIDEWALK:"sidewalk", FOOTPATH:"footpath",
    PARKING:"parking", PLAZA:"plaza", GREEN:"green", WATER:"water", ROAD:"road", CROSSING:"crossing"
}

def find_connected_components(walkable):
    """Find all connected components in the walkable grid"""
    H, W = walkable.shape
    visited = np.zeros_like(walkable, dtype=bool)
    components = []
    
    directions = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
    
    for y in range(H):
        for x in range(W):
            if walkable[y, x] == 1 and not visited[y, x]:
                # Start new component
                component = []
                queue = [(y, x)]
                visited[y, x] = True
                
                while queue:
                    cy, cx = queue.pop(0)
                    component.append((cy, cx))
                    
                    for dy, dx in directions:
                        ny, nx = cy + dy, cx + dx
                        if (0 <= ny < H and 0 <= nx < W and 
                            not visited[ny, nx] and walkable[ny, nx] == 1):
                            visited[ny, nx] = True
                            queue.append((ny, nx))
                
                components.append(component)
    
    # Sort by size (largest first)
    components.sort(key=len, reverse=True)
    return components

def analyze_barrier_between_points(semantic, walkable, start, goal, sample_points=20):
    """Analyze what's blocking the path between start and goal"""
    sy, sx = start
    gy, gx = goal
    
    print(f"\nAnalyzing barriers between {start} and {goal}")
    
    # Sample points along the line between start and goal
    for i in range(sample_points + 1):
        t = i / sample_points
        y = int(sy + t * (gy - sy))
        x = int(sx + t * (gx - sx))
        
        if 0 <= y < semantic.shape[0] and 0 <= x < semantic.shape[1]:
            sem_class = semantic[y, x]
            is_walkable = walkable[y, x]
            class_name = CLASS_NAMES.get(sem_class, f"unknown_{sem_class}")
            
            print(f"Point {i:2d}: ({y:3d}, {x:3d}) - {class_name:12s} - walkable: {is_walkable}")

def create_component_visualization(walkable, components, start, goal, output_path):
    """Create visualization showing different connected components"""
    H, W = walkable.shape
    
    # Create RGB image
    rgb = np.zeros((H, W, 3), dtype=np.uint8)
    
    # Gray for non-walkable
    rgb[walkable == 0] = (64, 64, 64)
    
    # Different colors for different components
    colors = [
        (255, 0, 0),    # Red for largest
        (0, 255, 0),    # Green for second largest
        (0, 0, 255),    # Blue for third largest
        (255, 255, 0),  # Yellow
        (255, 0, 255),  # Magenta
        (0, 255, 255),  # Cyan
        (255, 128, 0),  # Orange
        (128, 255, 0),  # Lime
        (128, 0, 255),  # Purple
        (255, 128, 128), # Light red
    ]
    
    for i, component in enumerate(components[:len(colors)]):
        color = colors[i]
        for y, x in component:
            rgb[y, x] = color
    
    # White for remaining small components
    for i, component in enumerate(components[len(colors):]):
        for y, x in component:
            rgb[y, x] = (255, 255, 255)
    
    img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(img)
    
    # Mark start and goal with larger circles
    sy, sx = start
    gy, gx = goal
    
    # Start in black circle with white border
    draw.ellipse((sx-8, sy-8, sx+8, sy+8), fill=(255, 255, 255))
    draw.ellipse((sx-6, sy-6, sx+6, sy+6), fill=(0, 0, 0))
    
    # Goal in black circle with white border
    draw.ellipse((gx-8, gy-8, gx+8, gy+8), fill=(255, 255, 255))
    draw.ellipse((gx-6, gy-6, gx+6, gy+6), fill=(0, 0, 0))
    
    img.save(output_path)
    print(f"Saved component visualization to {output_path}")

if __name__ == "__main__":
    out_dir = "out/society145_1km"
    
    # Load data
    semantic = np.load(os.path.join(out_dir, "semantic.npy"))
    nav_data = np.load(os.path.join(out_dir, "navgraph.npz"))
    walkable = nav_data['walkable']
    
    # Demo positions from the log
    start = (150, 283)
    goal = (130, 129)
    
    print("=== CONNECTED COMPONENTS ANALYSIS ===")
    components = find_connected_components(walkable)
    
    print(f"Found {len(components)} connected components")
    print("Top 10 components by size:")
    for i, comp in enumerate(components[:10]):
        print(f"  Component {i+1}: {len(comp)} cells")
    
    # Find which components contain start and goal
    start_comp = goal_comp = None
    for i, comp in enumerate(components):
        if start in comp:
            start_comp = i
        if goal in comp:
            goal_comp = i
    
    print(f"\nStart {start} is in component: {start_comp + 1 if start_comp is not None else 'None'}")
    print(f"Goal {goal} is in component: {goal_comp + 1 if goal_comp is not None else 'None'}")
    
    if start_comp is not None and goal_comp is not None:
        if start_comp == goal_comp:
            print("Start and goal are in the SAME component - this shouldn't happen!")
        else:
            print(f"Start and goal are in DIFFERENT components ({start_comp+1} vs {goal_comp+1})")
            print(f"Start component size: {len(components[start_comp])}")
            print(f"Goal component size: {len(components[goal_comp])}")
    
    # Analyze what's between start and goal
    analyze_barrier_between_points(semantic, walkable, start, goal)
    
    # Create visualization
    create_component_visualization(walkable, components, start, goal,
                                 os.path.join(out_dir, "components_debug.png"))
    
    # Additional analysis: what classes are walkable
    print(f"\n=== WALKABLE CLASSES ===")
    for class_id in range(10):
        class_mask = (semantic == class_id)
        walkable_in_class = np.sum(walkable[class_mask])
        total_in_class = np.sum(class_mask)
        if total_in_class > 0:
            pct = 100 * walkable_in_class / total_in_class
            print(f"{CLASS_NAMES[class_id]:12s}: {walkable_in_class:6d}/{total_in_class:6d} ({pct:5.1f}%) walkable")
