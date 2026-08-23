from typing import Dict, Any, Optional
from app.harness.sandbox import StatefulSandbox

def simulate_tool_response(tool_name: str, tool_args: Dict[str, Any], tool_schema: Dict[str, Any], scenario: Any, sandbox: Optional[StatefulSandbox] = None) -> Dict[str, Any]:
    # 1. Direct scripted override if provided in scenario definition
    if scenario.scripted_responses and tool_name in scenario.scripted_responses:
        return scenario.scripted_responses[tool_name]
        
    # 2. Stateful Sandbox execution (state transitions & consistency)
    if sandbox:
        return sandbox.execute_tool(tool_name, tool_args)
        
    # 3. Fallback deterministic response
    return {"status": "success", "tool": tool_name, "message": f"Executed {tool_name}"}

