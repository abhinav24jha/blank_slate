#!/usr/bin/env python3
"""
FAST DEMO: Generate real analytics.json in under 30 seconds total
"""

import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))

from simulation.scenario_models import ExperimentConfig
from simulation.experiment_runner import run_experiment
import uuid

def main():
    print("⚡ FAST DEMO: Real agent simulations -> analytics.json")
    
    cfg = ExperimentConfig(
        agent_count=15,  # Reasonable number
        duration_s=10.0,  # 10 seconds per scenario
        speed=3.0
    )
    
    exp_id = f'fast_{str(uuid.uuid4())[:6]}'
    scenarios = [
        'simulation/scenarios/baseline.json',
        'simulation/scenarios/society145_h001_convenience_cafe.json',
        'simulation/scenarios/society145_h003_market_square.json'
    ]
    
    print(f"📋 Experiment ID: {exp_id}")
    print(f"🤖 Agents: {cfg.agent_count}")
    print(f"⏱️  Duration per scenario: {cfg.duration_s}s")
    print(f"⚡ Running {len(scenarios)} scenarios IN PARALLEL...")
    
    start_time = time.time()
    results = run_experiment(exp_id, scenarios, cfg)
    total_time = time.time() - start_time
    
    analytics_path = f'simulation/out/experiments/{exp_id}/analytics.json'
    
    print(f"\n🎉 DEMO COMPLETE in {total_time:.1f}s!")
    print(f"📊 Analytics: {analytics_path}")
    print(f"📈 Scenarios completed: {len(results)}")
    
    # Show the path for easy access
    print(f"\n💡 To view analytics:")
    print(f"   cat {analytics_path}")

if __name__ == "__main__":
    main()
