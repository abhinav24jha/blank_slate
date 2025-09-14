#!/usr/bin/env python3
"""
Quick warmup script to prepare the system for demo.
Run this before your demo to ensure everything is loaded and ready.
"""

import requests
import time
import sys

def warmup_brain_server():
    """Warmup the brain server model."""
    try:
        print("🔥 Warming up brain server...")
        response = requests.post("http://127.0.0.1:9000/warmup", timeout=120)
        if response.status_code == 200:
            result = response.json()
            if result.get("status") == "warmed":
                print("✅ Brain server model warmed up successfully!")
                return True
            else:
                print("❌ Brain server warmup failed")
                return False
        else:
            print(f"❌ Brain server warmup request failed: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Could not connect to brain server: {e}")
        print("💡 Make sure brain server is running on port 9000")
        return False

def test_agent_decision():
    """Test a quick agent decision to ensure everything works."""
    try:
        print("🧠 Testing agent decision making...")
        
        # Start a test run
        start_response = requests.post("http://127.0.0.1:9000/start_run", json={
            "hypothesisId": "warmup-test",
            "seed": 12345,
            "speed": 1.0
        }, timeout=30)
        
        if start_response.status_code != 200:
            print(f"❌ Could not start test run: {start_response.status_code}")
            return False
        
        run_id = start_response.json()["runId"]
        
        # Test a decision
        decision_response = requests.post("http://127.0.0.1:9000/decide", json={
            "runId": run_id,
            "agents": [{
                "id": "test_agent",
                "role": "student",
                "pos": [100, 100],
                "needs": {"caffeine": 0.8, "social": 0.6}
            }],
            "context": {}
        }, timeout=60)
        
        if decision_response.status_code == 200:
            decisions = decision_response.json().get("decisions", [])
            if decisions:
                print("✅ Agent decision test successful!")
                print(f"   Agent thought: '{decisions[0].get('thought', 'N/A')}'")
                return True
        
        print("❌ Agent decision test failed")
        return False
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Agent decision test failed: {e}")
        return False

def main():
    print("🚀 Demo Warmup Script")
    print("=" * 40)
    
    # Check if brain server is running
    try:
        requests.get("http://127.0.0.1:9000", timeout=5)
    except:
        print("❌ Brain server not running!")
        print("💡 Start it with: uvicorn simulation.brain_server:app --host 127.0.0.1 --port 9000 --reload")
        sys.exit(1)
    
    success = True
    
    # Warmup model
    if not warmup_brain_server():
        success = False
    
    # Test decision making
    if not test_agent_decision():
        success = False
    
    print("=" * 40)
    if success:
        print("🎉 Demo warmup completed successfully!")
        print("✅ Your system is ready for a smooth demo!")
        print("\n💡 Now open your viewer at: http://localhost:8080/simulation/viewer/index.html")
    else:
        print("❌ Demo warmup had issues - check the logs above")
        sys.exit(1)

if __name__ == "__main__":
    main()
