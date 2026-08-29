from typing import Dict, Any, Optional
from app.harness.sandbox import StatefulSandbox

def simulate_tool_response(tool_name: str, tool_args: Dict[str, Any], tool_schema: Dict[str, Any], scenario: Any, sandbox: Optional[StatefulSandbox] = None) -> Dict[str, Any]:
    # 1. Direct scripted override if provided in scenario definition
    if scenario.scripted_responses and tool_name in scenario.scripted_responses:
        return scenario.scripted_responses[tool_name]
        
    # A non-empty schema means the tool is part of the agent's declared toolset.
    # An empty schema means the agent invoked a name it never declared (a
    # hallucinated tool) — the sandbox must not reward that with a fake success.
    declared = bool(tool_schema)

    # 2. Stateful Sandbox execution (state transitions & consistency)
    if sandbox:
        return sandbox.execute_tool(tool_name, tool_args, declared=declared)

    # 3. Fallback deterministic response
    if not declared:
        return {"status": "ERROR", "tool": tool_name, "found": False,
                "error": f"Unknown tool '{tool_name}': not a registered capability for this agent."}
    return {"status": "success", "tool": tool_name, "message": f"Executed {tool_name}"}

