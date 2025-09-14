#!/usr/bin/env python3
"""
Simple script to clean existing research data files.
Run this before testing to ensure fresh research is conducted.
"""

import os
import glob

def clean_data():
    """Remove all existing research data files."""
    data_dir = "./data"
    
    # Patterns to match existing research files
    patterns = [
        "*.evidence.json",
        "*.rounds.json", 
        "*.report.json",
        "*.report.md"
    ]
    
    cleaned_files = []
    
    for pattern in patterns:
        files = glob.glob(os.path.join(data_dir, pattern))
        for file_path in files:
            try:
                os.remove(file_path)
                cleaned_files.append(file_path)
                print(f"🗑️  Removed: {file_path}")
            except Exception as e:
                print(f"❌ Error removing {file_path}: {e}")
    
    if cleaned_files:
        print(f"✅ Cleaned {len(cleaned_files)} existing files")
    else:
        print(f"ℹ️  No existing files to clean")
    
    return cleaned_files

if __name__ == "__main__":
    clean_data()
