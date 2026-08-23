import urllib.request
import urllib.error
import json
import time

base_url = "http://127.0.0.1:8000"

print("Waiting for server to start...")
for _ in range(10):
    try:
        req = urllib.request.Request(f"{base_url}/health")
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                break
    except:
        time.sleep(1)

# 1. Generate scenarios
with open("demo_agents/devops_bot/system_prompt.txt") as f:
    sys_prompt = f.read()

with open("demo_agents/devops_bot/tools.json") as f:
    tools = json.load(f)

payload = {
    "system_prompt": sys_prompt,
    "tools": tools,
    "task_domain": "devops",
    "count_per_category": {
        "indirect_injection": 1
    }
}
print("Running scenario generation...")
req = urllib.request.Request(f"{base_url}/api/scenarios/generate", data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(req) as resp:
        print("Scenario gen response:", resp.status)
        scenarios = json.loads(resp.read().decode())
        print(f"Generated {len(scenarios)} scenarios.")
except urllib.error.HTTPError as e:
    print("Scenario gen response:", e.code)
    print("Error parsing scenario response:", e.read().decode())
    scenarios = []

if not scenarios:
    print("No scenarios, exiting.")
    exit(1)

# 2. Execute runs
scenario_ids = [s["scenario_id"] for s in scenarios]
exec_payload = {
    "scenario_ids": scenario_ids,
    "agent_version": "devops_bot_v1",
    "system_prompt": sys_prompt,
    "tools": tools
}
print("Running execution...")
req = urllib.request.Request(f"{base_url}/api/runs/execute", data=json.dumps(exec_payload).encode(), headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(req) as resp:
        print("Execution response:", resp.status)
        runs = json.loads(resp.read().decode())
        print(f"Executed {len(runs)} runs.")
except urllib.error.HTTPError as e:
    print("Execution response:", e.code)
    print("Error executing runs:", e.read().decode())
    runs = []

if not runs:
    print("No runs, exiting.")
    exit(1)

# 3. Classify runs
run_ids = [r["run_id"] for r in runs]
class_payload = {
    "run_ids": run_ids,
    "tools": tools
}
print("Running classification...")
req = urllib.request.Request(f"{base_url}/api/classify", data=json.dumps(class_payload).encode(), headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(req) as resp:
        print("Classify response:", resp.status)
        print("Classification complete.")
except urllib.error.HTTPError as e:
    print("Classify response:", e.code)
    print("Error classifying:", e.read().decode())
