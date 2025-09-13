#!/usr/bin/env python3
"""
Debug script to analyze POI-building mismatches
"""

import numpy as np
import json
from PIL import Image, ImageDraw
import os

def analyze_poi_building_mismatch():
    out_dir = "out/society145_1km"
    
    # Load data
    semantic = np.load(os.path.join(out_dir, "semantic.npy"))
    feature_id = np.load(os.path.join(out_dir, "feature_id.npy"))
    
    with open(os.path.join(out_dir, "pois.json"), 'r') as f:
        pois = json.load(f)
    
    with open(os.path.join(out_dir, "feature_table.json"), 'r') as f:
        features = json.load(f)
    
    H, W = semantic.shape
    class_names = {0:'void', 1:'building', 2:'sidewalk', 3:'footpath', 4:'parking', 5:'plaza', 6:'green', 7:'water', 8:'road', 9:'crossing'}
    
    print("=== POI-Building Mismatch Analysis ===")
    
    # Count POIs by semantic class they sit on
    poi_by_class = {}
    building_pois = 0
    non_building_pois = 0
    
    for poi in pois:
        loc = poi.get('snapped') or poi
        ix, iy = loc['ix'], loc['iy']
        
        if 0 <= ix < W and 0 <= iy < H:
            sem_class = semantic[iy, ix]
            class_name = class_names.get(sem_class, f'unknown_{sem_class}')
            
            if class_name not in poi_by_class:
                poi_by_class[class_name] = 0
            poi_by_class[class_name] += 1
            
            if sem_class == 1:  # BUILDING
                building_pois += 1
            else:
                non_building_pois += 1
    
    print(f"POIs on buildings: {building_pois}")
    print(f"POIs NOT on buildings: {non_building_pois}")
    print("\nPOIs by semantic class:")
    for class_name, count in sorted(poi_by_class.items(), key=lambda x: x[1], reverse=True):
        print(f"  {class_name}: {count}")
    
    # Create visualization
    rgb = np.zeros((H, W, 3), dtype=np.uint8)
    palette = {
        0:(240,240,240), 1:(60,60,60), 2:(230,230,230), 3:(200,200,200),
        4:(210,210,160), 5:(235,215,160), 6:(140,190,140), 7:(150,180,220),
        8:(120,120,120), 9:(250,250,120)
    }
    
    for cls, color in palette.items():
        rgb[semantic == cls] = color
    
    img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(img)
    
    # Mark POIs by their underlying class
    colors = {
        'building': (0, 255, 0),     # Green - good
        'plaza': (255, 255, 0),      # Yellow - questionable
        'road': (255, 0, 0),         # Red - bad
        'footpath': (255, 165, 0),   # Orange - questionable
        'parking': (255, 192, 203),  # Pink - questionable
        'sidewalk': (173, 216, 230), # Light blue - questionable
    }
    
    for poi in pois:
        loc = poi.get('snapped') or poi
        ix, iy = loc['ix'], loc['iy']
        
        if 0 <= ix < W and 0 <= iy < H:
            sem_class = semantic[iy, ix]
            class_name = class_names.get(sem_class, 'unknown')
            color = colors.get(class_name, (128, 128, 128))
            
            # Draw larger circle for better visibility
            draw.ellipse((ix-3, iy-3, ix+3, iy+3), fill=color, outline=(0,0,0))
    
    img.save(os.path.join(out_dir, "poi_building_debug.png"))
    print(f"\nSaved visualization to {os.path.join(out_dir, 'poi_building_debug.png')}")
    print("Legend:")
    print("  Green = POI on building (good)")
    print("  Yellow = POI on plaza (may need building)")
    print("  Red = POI on road (likely missing building)")
    print("  Orange = POI on footpath (may need building)")
    print("  Pink = POI on parking (may need building)")

if __name__ == "__main__":
    analyze_poi_building_mismatch()
