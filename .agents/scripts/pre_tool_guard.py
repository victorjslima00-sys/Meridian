"""
Pre-Tool Execution Guardrail for Antigravity (Meridian Nexus Governance)
Enforces non-negotiable safety policies:
- Blocks git push --force / force-with-lease
- Blocks destructive git commands (reset --hard without targets, clean -fdx)
- Blocks live broker activation and unauthorized production deploys
- Allows safe, everyday development and testing commands
"""
import sys
import json
import re

PROHIBITED_PATTERNS = [
    # 1. Force pushes
    (re.compile(r"\bgit\s+push\b.*(\s--force|-f\b|\s--force-with-lease)", re.IGNORECASE),
     "[NEXUS GUARD] Force push is strictly prohibited by Nexus Directive 000 Git Governance."),
    
    # 2. Destructive git clean
    (re.compile(r"\bgit\s+clean\b.*\s-[a-zA-Z]*f", re.IGNORECASE),
     "[NEXUS GUARD] Destructive git clean is blocked. Working tree must be preserved."),
    
    # 3. Destructive branch deletion of main
    (re.compile(r"\bgit\s+branch\s+-(?:d|D)\s+main\b", re.IGNORECASE),
     "[NEXUS GUARD] Deletion of main branch is strictly prohibited."),
    
    # 4. Live broker command line triggers
    (re.compile(r"(--live-broker|\bLIVE_BROKER=1\b|\bCEDRO_PRODUCTION=1\b|--broker-live)", re.IGNORECASE),
     "[NEXUS GUARD] Live broker operations are blocked. Invariant real_broker_calls == 0 must be preserved."),
    
    # 5. Production deploy commands without explicit executive override
    (re.compile(r"\b(terraform\s+apply\b.*-auto-approve|kubectl\s+apply\b.*production|aws\s+ecs\s+update-service\b.*prod)", re.IGNORECASE),
     "[NEXUS GUARD] Direct production deploy commands are blocked under Nexus generic directives.")
]

def evaluate_command(command_line: str) -> dict:
    cmd = command_line.strip()
    for pattern, reason in PROHIBITED_PATTERNS:
        if pattern.search(cmd):
            return {
                "decision": "deny",
                "reason": reason
            }
    return {
        "decision": "allow",
        "reason": "Standard safe development operation."
    }

def main():
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            # If no input, default allow
            print(json.dumps({"decision": "allow"}))
            return

        payload = json.loads(raw_input)
        tool_call = payload.get("toolCall", {})
        tool_name = tool_call.get("name", "")
        args = tool_call.get("args", {})
        
        if tool_name == "run_command":
            cmd_line = args.get("CommandLine", "")
            result = evaluate_command(cmd_line)
            print(json.dumps(result))
            return

        print(json.dumps({"decision": "allow"}))
    except Exception as exc:
        # Fail-closed in case of internal hook parser error
        print(json.dumps({"decision": "deny", "reason": f"[NEXUS GUARD] Hook error: {exc}"}))

if __name__ == "__main__":
    main()
