#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate realistic 2D map tiles using Gemini (aka Nano Banana) Image API

This replaces the placeholder atlas.png with proper top-down 2D map assets
that look like an actual map rather than colored squares.

Usage:
    python generate_assets.py --api-key YOUR_KEY --out-dir out/society145_1km/tiles

Generates:
- Individual tile PNGs for each semantic class + variants
- Packed atlas.png to replace the placeholder
- Updates manifest.json with new frames

Implementation notes:
- Uses Google Gen AI SDK (`from google import genai`) as shown in the official docs.
- Model: "gemini-2.5-flash-image-preview" (aka Nano Banana). You can change the MODEL
  constant if needed when a stable tag supersedes the preview.
- The API does not take width/height; we request a seamless / tileable texture in the
  prompt and then resize to TILE_SIZE for the atlas.
- All generated images include SynthID per Google policy.
"""

import os
import json
import argparse
import math
from typing import Dict, List, Tuple, Optional
import time
from PIL import Image
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# --- NEW: Gemini (Nano Banana) SDK imports ---
try:
    from google import genai
except ImportError:
    genai = None  # We'll error gracefully if the SDK isn't installed

# Configuration
VARIANTS = 3
TILE_SIZE = 64  # Final atlas tile size
MODEL = "gemini-2.5-flash-image-preview"  # per docs; update if/when stable

# Semantic classes and their descriptions for Gemini - CLEAN 2D GAME STYLE
TILE_PROMPTS: Dict[str, str] = {
    "void": "Clean flat gray pavement tile, 2D game art style, top-down orthographic view, pixel art aesthetic, simple solid color with minimal detail, seamless tileable pattern.",
    "building": "2D game building tile, clean geometric rooftop, flat colors, top-down orthographic view, simple architectural details, pixel art style, seamless tileable pattern.",
    "sidewalk": "Clean light gray sidewalk tile, 2D game art style, top-down view, simple flat design, minimal texture, pixel art aesthetic, seamless tileable pattern.",
    "footpath": "Brown dirt path tile, 2D game art style, top-down view, simple earth tone colors, clean pixel art aesthetic, seamless tileable pattern.",
    "parking": "Dark gray asphalt parking tile with white line markings, 2D game art style, clean geometric design, top-down view, pixel art aesthetic, seamless tileable pattern.",
    "plaza": "Light stone plaza tile, 2D game art style, clean flat colors, top-down orthographic view, simple paving pattern, pixel art aesthetic, seamless tileable pattern.",
    "green": "Bright green grass tile, 2D game art style, clean flat colors, top-down view, simple nature texture, pixel art aesthetic, seamless tileable pattern.",
    "water": "Clean blue water tile, 2D game art style, simple flat blue color with subtle wave pattern, top-down view, pixel art aesthetic, seamless tileable pattern.",
    "road": "Dark gray asphalt road tile, 2D game art style, clean flat colors, top-down view, simple road texture, pixel art aesthetic, seamless tileable pattern.",
    "crossing": "White striped crosswalk tile on dark asphalt, 2D game art style, clean geometric stripes, top-down view, pixel art aesthetic, seamless tileable pattern."
}

VARIANT_MODIFIERS = [
    "lightly weathered",
    "clean and new",
    "with subtle wear patterns"
]



class NanoBananaGenerator:
    """
    Thin wrapper over Gemini (aka Nano Banana) image generation per docs:
    https://ai.google.dev/gemini-api/docs/image-generation
    """
    def __init__(self, api_key: Optional[str] = None):
        # The Gen AI client reads GOOGLE_API_KEY from the environment.
        if api_key:
            os.environ["GOOGLE_API_KEY"] = api_key
        # Create client; no args needed if env var is set.
        self.client = genai.Client()
        self.lock = threading.Lock()  # Thread safety for API calls

    def generate_tile(self, prompt: str) -> Optional[Image.Image]:
        """
        Generate a single image from text using Gemini.
        The SDK returns candidates; image bytes are in part.inline_data.data (base64 bytes).
        """
        with self.lock:  # Ensure thread safety
            try:
                # Important: pass the prompt as `contents`, matching the docs
                resp = self.client.models.generate_content(
                    model=MODEL,
                    contents=[prompt]
                )

                # Check if we have candidates
                if not resp.candidates:
                    print(f"[Gemini] No candidates returned for prompt")
                    return None

                # Extract the first image part with inline_data
                for part in resp.candidates[0].content.parts:
                    if hasattr(part, "inline_data") and part.inline_data is not None:
                        data = part.inline_data.data  # bytes (already base64-decoded by SDK)
                        return Image.open(io.BytesIO(data)).convert("RGBA")

                # Some generations can return intermediate text; if no image part returned:
                print(f"[Gemini] No image data in response parts")
                return None

            except Exception as e:
                print(f"[Gemini] Generation error: {e}")
                print(f"[Gemini] Error type: {type(e)}")
                return None

    def generate_variant(self, base_prompt: str, modifier: str) -> Optional[Image.Image]:
        # Enhanced prompt for clean 2D game style
        full_prompt = (
            f"{base_prompt} Style variant: {modifier}. "
            f"IMPORTANT: Clean 2D video game art style like classic RPGs or strategy games. "
            f"Flat colors, simple shapes, no realistic textures or noise. "
            f"Top-down orthographic view only, no perspective or 3D effects. "
            f"Clear readable design, not photorealistic. "
            f"No text, watermarks, logos, or UI elements. "
            f"Perfect seamless tileable pattern that repeats cleanly."
        )
        return self.generate_tile(full_prompt)


def create_fallback_tile(class_name: str, variant: int, size: int = TILE_SIZE) -> Image.Image:
    """Create clean 2D game-style fallback tiles if Gemini fails"""
    from PIL import ImageDraw
    
    # Clean, flat colors like the reference image
    colors = {
        "void": [(180, 180, 180), (160, 160, 160), (200, 200, 200)],
        "building": [(120, 80, 60), (100, 70, 50), (140, 90, 70)],     # Brown building colors
        "sidewalk": [(200, 200, 200), (180, 180, 180), (220, 220, 220)],
        "footpath": [(160, 120, 80), (140, 100, 60), (180, 140, 100)], # Brown dirt paths
        "parking": [(100, 100, 100), (80, 80, 80), (120, 120, 120)],
        "plaza": [(150, 150, 150), (130, 130, 130), (170, 170, 170)],
        "green": [(60, 140, 60), (50, 120, 50), (70, 160, 70)],        # Bright grass green
        "water": [(80, 120, 200), (60, 100, 180), (100, 140, 220)],    # Clear blue water
        "road": [(80, 80, 80), (60, 60, 60), (100, 100, 100)],
        "crossing": [(200, 200, 200), (180, 180, 180), (220, 220, 220)]
    }

    base_color = colors.get(class_name, [(128, 128, 128)] * 3)[variant]
    img = Image.new("RGBA", (size, size), base_color + (255,))
    draw = ImageDraw.Draw(img)

    # Create proper building sprites - different variants for different parts
    if class_name == "building":
        roof_color = tuple(int(c * 0.9) for c in base_color)  # Darker roof
        wall_color = base_color
        window_color = (200, 230, 255)  # Light blue windows
        
        if variant == 0:  # Basic building tile - no door
            # Roof (top portion)
            draw.rectangle([0, 0, size, size//3], fill=roof_color)
            # Walls (bottom portion)  
            draw.rectangle([0, size//3, size, size], fill=wall_color)
            # Single window in center
            window_size = size // 6
            wx, wy = size//2, size//2 + size//6
            draw.rectangle([wx-window_size//2, wy-window_size//2, 
                          wx+window_size//2, wy+window_size//2], fill=window_color)
                          
        elif variant == 1:  # Building with door (entrance tile)
            # Roof (top portion)
            draw.rectangle([0, 0, size, size//3], fill=roof_color)
            # Walls (bottom portion)  
            draw.rectangle([0, size//3, size, size], fill=wall_color)
            # Door (bottom center) - only on variant 1
            door_color = (80, 40, 20)
            door_w, door_h = size//4, size//3
            door_x = size//2 - door_w//2
            door_y = size - door_h
            draw.rectangle([door_x, door_y, door_x + door_w, door_y + door_h], fill=door_color)
            
        else:  # variant == 2: Building corner/edge
            # Roof (top portion)
            draw.rectangle([0, 0, size, size//3], fill=roof_color)
            # Walls (bottom portion)  
            draw.rectangle([0, size//3, size, size], fill=wall_color)
            # Two small windows
            window_size = size // 8
            for i, (wx, wy) in enumerate([(size//4, size//2), (3*size//4, 3*size//4)]):
                draw.rectangle([wx-window_size//2, wy-window_size//2, 
                              wx+window_size//2, wy+window_size//2], fill=window_color)
        
    elif class_name == "crossing":
        # Add white stripes for crosswalk
        stripe_width = size // 8
        for i in range(0, size, stripe_width * 2):
            draw.rectangle([i, 0, i + stripe_width, size], fill=(255, 255, 255, 255))
    
    elif class_name == "parking":
        # Add simple parking lines
        draw.line([0, size//2, size, size//2], fill=(255, 255, 255, 255), width=2)
        draw.line([size//2, 0, size//2, size], fill=(255, 255, 255, 255), width=2)
    
    elif class_name == "green":
        # Add some tree/vegetation details
        tree_color = (40, 100, 40)
        for i in range(3):
            for j in range(3):
                if (i + j) % 2 == 0:  # Scattered pattern
                    tx = size//6 + i * size//3 + (variant * 7) % 10
                    ty = size//6 + j * size//3 + (variant * 11) % 10
                    draw.ellipse([tx-3, ty-3, tx+3, ty+3], fill=tree_color)
    
    elif class_name == "water":
        # Add subtle wave lines
        wave_color = tuple(int(c * 1.1) for c in base_color[:3])
        for i in range(0, size, 8):
            y = size//2 + int(4 * math.sin(i * 0.3 + variant))
            draw.line([0, y, size, y], fill=wave_color, width=1)

    return img


def generate_single_tile(args: Tuple) -> Tuple[str, Optional[Image.Image], Dict]:
    """Generate a single tile - designed for parallel execution"""
    (class_id, class_name, base_prompt, variant, generator) = args
    
    tile_name = f"{class_name}_v{variant}"
    mod = VARIANT_MODIFIERS[variant % len(VARIANT_MODIFIERS)]
    
    # Compose the final prompt for this variant
    prompt = (
        f"{base_prompt} "
        f"Square composition. "
        f"Uniform scale at ~{TILE_SIZE}×{TILE_SIZE} target (will be resized)."
    )
    
    img: Optional[Image.Image] = None
    if generator:
        img = generator.generate_variant(prompt, mod)
        if img is not None:
            print(f"  ✓ Generated {tile_name} via Gemini")
        else:
            print(f"  ✗ Gemini failed for {tile_name}, using fallback")
    
    if img is None:
        img = create_fallback_tile(class_name, variant, TILE_SIZE)
        print(f"  → Created fallback {tile_name}")
    
    # Ensure target size & mode
    if img.size != (TILE_SIZE, TILE_SIZE):
        img = img.resize((TILE_SIZE, TILE_SIZE), Image.LANCZOS)
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    
    frame = {
        "name": tile_name,
        "class": class_name,
        "class_id": class_id,
        "variant": variant,
        "tile_index": class_id * VARIANTS + variant
    }
    
    return tile_name, img, frame

def generate_all_assets(api_key: Optional[str], output_dir: str, max_workers: int = 8) -> int:
    """Generate all tile assets and create new atlas using parallel execution"""
    os.makedirs(output_dir, exist_ok=True)

    generator: Optional[NanoBananaGenerator] = None
    if api_key and genai is not None:
        try:
            generator = NanoBananaGenerator(api_key)
            print(f"Initialized Gemini client with model: {MODEL}")
        except Exception as e:
            print(f"Warning: Could not initialize Gemini client ({e}); using fallbacks only.")
    elif api_key and genai is None:
        print("Warning: google-genai SDK not available; using fallbacks only.")
    else:
        print("No API key provided; using fallback tiles only.")

    # Prepare all generation tasks
    tasks = []
    for class_id, (class_name, base_prompt) in enumerate(TILE_PROMPTS.items()):
        for variant in range(VARIANTS):
            tasks.append((class_id, class_name, base_prompt, variant, generator))

    tiles: Dict[str, Image.Image] = {}
    frames: List[Dict] = []

    print(f"Generating {len(tasks)} tiles in parallel (max_workers={max_workers})...")
    
    # Execute in parallel
    if generator:
        # Use threading for API calls (I/O bound)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {executor.submit(generate_single_tile, task): task for task in tasks}
            
            for future in as_completed(future_to_task):
                try:
                    tile_name, img, frame = future.result()
                    tiles[tile_name] = img
                    frames.append(frame)
                except Exception as e:
                    task = future_to_task[future]
                    class_name, variant = task[1], task[3]
                    print(f"  ✗ Failed to generate {class_name}_v{variant}: {e}")
                    # Create fallback for failed task
                    tile_name = f"{class_name}_v{variant}"
                    img = create_fallback_tile(class_name, variant, TILE_SIZE)
                    tiles[tile_name] = img
                    frames.append({
                        "name": tile_name,
                        "class": class_name, 
                        "class_id": task[0],
                        "variant": variant,
                        "tile_index": task[0] * VARIANTS + variant
                    })
    else:
        # No generator, just create fallbacks quickly
        for task in tasks:
            tile_name, img, frame = generate_single_tile(task)
            tiles[tile_name] = img
            frames.append(frame)

    # Pack atlas
    print("Creating atlas...")
    cols = VARIANTS
    rows = len(TILE_PROMPTS)
    atlas_width = cols * TILE_SIZE
    atlas_height = rows * TILE_SIZE
    atlas = Image.new("RGBA", (atlas_width, atlas_height), (0, 0, 0, 0))

    for frame in frames:
        class_id = frame["class_id"]
        variant = frame["variant"]
        x = variant * TILE_SIZE
        y = class_id * TILE_SIZE
        frame.update({"x": x, "y": y, "w": TILE_SIZE, "h": TILE_SIZE})
        atlas.paste(tiles[frame["name"]], (x, y))

    atlas_path = os.path.join(output_dir, "atlas.png")
    atlas.save(atlas_path)
    print(f"Saved atlas: {atlas_path}")

    # Update manifest if present
    manifest_path = os.path.join(output_dir, "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        manifest["atlas"] = {
            "image": "atlas.png",
            "width": atlas_width,
            "height": atlas_height,
            "frames": frames
        }
        manifest["tileSize"] = TILE_SIZE

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        print(f"Updated manifest: {manifest_path}")

    print(f"Generated {len(tiles)} tiles successfully!")
    return len(tiles)


def main():
    parser = argparse.ArgumentParser(description="Generate map tiles using Gemini (aka Nano Banana)")
    parser.add_argument("--api-key", help="Google AI (Gemini) API key (optional; fallbacks used if omitted)")
    parser.add_argument("--out-dir", default="out/society145_1km/tiles", help="Output directory")
    parser.add_argument("--workers", type=int, default=8, help="Max parallel workers for generation (default: 8)")
    args = parser.parse_args()

    if not args.api_key:
        print("Warning: No API key provided, using improved fallback tiles only.")

    try:
        count = generate_all_assets(args.api_key, args.out_dir, max_workers=args.workers)
        print(f"Done! Generated {count} tiles.")
    except Exception as e:
        print(f"Fatal error: {e}")


if __name__ == "__main__":
    main()