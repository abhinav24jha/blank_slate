#!/usr/bin/env python3
"""
Script to clean existing research data and run the deep research pipeline.
This ensures fresh research is conducted instead of loading cached data.
"""

import os
import glob
import subprocess
import sys
from pathlib import Path

def clean_existing_data():
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
    
    return cleaned_files

def run_research_pipeline(objective, prefix=None):
    """Run the deep research pipeline with the given objective."""
    try:
        print(f"🔬 Starting research pipeline for: {objective}")
        
        # Set up the command
        cmd = [sys.executable, "deep_research_pipeline.py", objective]
        if prefix:
            cmd.append(prefix)
        
        # Run the pipeline
        result = subprocess.run(
            cmd,
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        if result.returncode == 0:
            print(f"✅ Research pipeline completed successfully")
            return True, result.stdout
        else:
            print(f"❌ Research pipeline failed with return code {result.returncode}")
            print(f"Error output: {result.stderr}")
            return False, result.stderr
            
    except subprocess.TimeoutExpired:
        print(f"⏰ Research pipeline timed out after 5 minutes")
        return False, "Pipeline timed out"
    except Exception as e:
        print(f"❌ Error running research pipeline: {e}")
        return False, str(e)

def main():
    """Main function to clean data and run research."""
    if len(sys.argv) < 2:
        print("Usage: python clean_and_research.py <objective> [prefix]")
        sys.exit(1)
    
    objective = sys.argv[1]
    prefix = sys.argv[2] if len(sys.argv) > 2 else None
    
    print(f"🧹 Cleaning existing research data...")
    cleaned_files = clean_existing_data()
    
    if cleaned_files:
        print(f"✅ Cleaned {len(cleaned_files)} existing files")
    else:
        print(f"ℹ️  No existing files to clean")
    
    print(f"🔬 Running fresh research pipeline...")
    success, output = run_research_pipeline(objective, prefix)
    
    if success:
        print(f"🎉 Research completed successfully!")
        print(f"📊 Output: {output}")
    else:
        print(f"💥 Research failed: {output}")
        sys.exit(1)

if __name__ == "__main__":
    main()
