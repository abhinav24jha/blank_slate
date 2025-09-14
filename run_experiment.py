#!/usr/bin/env python3
"""
Quick experiment runner for Society145 scenarios.
Usage: python run_experiment.py [--agents N] [--scenarios h001,h002,h003]
"""

import argparse
import json
import uuid
from simulation.experiment_runner import run_experiment
from simulation.scenario_models import ExperimentConfig


def main():
    parser = argparse.ArgumentParser(description="Run Society145 scenario experiments")
    parser.add_argument("--agents", type=int, default=10, help="Number of agents (default: 10)")
    parser.add_argument("--duration", type=float, default=30.0, help="Duration in seconds (default: 30)")
    parser.add_argument("--scenarios", type=str, default="baseline,h001", 
                       help="Comma-separated scenario list: baseline,h001,h002,h003,h004 (default: baseline,h001)")
    args = parser.parse_args()

    # Map scenario names to files
    scenario_map = {
        "baseline": "simulation/scenarios/baseline.json",
        "h001": "simulation/scenarios/society145_h001_convenience_cafe.json", 
        "h002": "simulation/scenarios/society145_h002_clubhouse.json",
        "h003": "simulation/scenarios/society145_h003_market_square.json",
        "h004": "simulation/scenarios/society145_h004_food_hall.json"
    }
    
    requested = args.scenarios.split(",")
    scenario_files = []
    for name in requested:
        name = name.strip()
        if name in scenario_map:
            scenario_files.append(scenario_map[name])
        else:
            print(f"Warning: Unknown scenario '{name}', skipping")
    
    if not scenario_files:
        print("Error: No valid scenarios specified")
        return
    
    print(f"🚀 Running experiment with {args.agents} agents for {args.duration}s")
    print(f"📋 Scenarios: {', '.join(requested)}")
    print(f"🧠 Ensure brain server is running: uvicorn simulation.brain_server:app --host 127.0.0.1 --port 9000 --reload")
    print()

    config = ExperimentConfig(
        agent_count=args.agents,
        duration_s=args.duration
    )
    
    exp_id = f"exp_{str(uuid.uuid4())[:8]}"
    
    try:
        results = run_experiment(exp_id, scenario_files, config)
        
        print("✅ Experiment completed!")
        print(f"📊 Results saved to: simulation/out/experiments/{exp_id}/")
        print()
        
        # Print summary
        baseline_data = None
        for filename, data in results.items():
            if "baseline" in filename:
                baseline_data = data
                break
        
        print("📈 RESULTS SUMMARY:")
        print("-" * 50)
        
        for filename, data in results.items():
            scenario = data.get("scenario", "unknown")
            decisions = data.get("decisions", 0)
            categories = data.get("by_category", {})
            
            print(f"\n🏗️  {scenario}:")
            print(f"   Decisions: {decisions}")
            print(f"   Categories: {categories}")
            
            # Show difference from baseline
            if baseline_data and filename != list(results.keys())[0]:
                baseline_cats = baseline_data.get("by_category", {})
                print("   Δ from baseline:")
                all_cats = set(categories.keys()) | set(baseline_cats.keys())
                for cat in sorted(all_cats):
                    base_count = baseline_cats.get(cat, 0)
                    scen_count = categories.get(cat, 0)
                    diff = scen_count - base_count
                    if diff != 0:
                        print(f"     {cat}: {diff:+d}")
        
        print(f"\n📁 Detailed results: simulation/out/experiments/{exp_id}/")
        
    except Exception as e:
        print(f"❌ Experiment failed: {e}")
        print("💡 Make sure brain server is running on port 9000")


if __name__ == "__main__":
    main()
