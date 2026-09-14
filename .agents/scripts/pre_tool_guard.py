"""
Pre-Tool Execution Guardrail for Antigravity (Meridian Nexus Governance)

Enforces non-negotiable safety policies:
1. Git Force Push: Blocks git push --force, -f, --force-with-lease
2. Git Destructive Reset: Blocks git reset --hard across all target variations
3. Git Destructive Clean: Blocks git clean with force flags (-f, -fdx, etc.)
4. Git Protected Branch Deletion: Blocks git branch -d/-D on main
5. Live Broker Activation: Blocks flags/variables triggering real broker trading
6. Unauthorized Production Deploy: Blocks terraform apply auto-approve, prod kubectl, prod aws ecs, deploy_prod
7. Everyday Development: Transparently allows safe testing, git staging/commit/push, and paper execution.
"""
from __future__ import annotations

import json
import re
import sys

PROHIBITED_PATTERNS = [
    # 1. Force pushes
    (
        re.compile(r"\bgit\b.*?\bpush\b.*(\s--force\b|\s-f\b|\s--force-with-lease\b)", re.IGNORECASE),
        "[NEXUS GUARD] Force push is strictly prohibited by Nexus Directive 000 Git Governance.",
    ),
    # 2. Destructive git reset --hard
    (
        re.compile(r"\bgit\b.*?\breset\b.*?\s--hard\b", re.IGNORECASE),
        "[NEXUS GUARD] Destructive git reset --hard is strictly prohibited by Nexus Directive 000 Git Governance.",
    ),
    # 3. Destructive git clean
    (
        re.compile(r"\bgit\b.*?\bclean\b.*?\s-[a-zA-Z]*f", re.IGNORECASE),
        "[NEXUS GUARD] Destructive git clean is blocked. Working tree must be preserved.",
    ),
    # 4. Destructive branch deletion of main
    (
        re.compile(r"\bgit\b.*?\bbranch\b.*?\s-(?:d|D)\s+main\b", re.IGNORECASE),
        "[NEXUS GUARD] Deletion of main branch is strictly prohibited.",
    ),
    # 5. Live broker command line triggers
    (
        re.compile(r"(--live-broker\b|\bLIVE_BROKER=1\b|\bCEDRO_PRODUCTION=1\b|--broker-live\b|\bMT5_LIVE=1\b)", re.IGNORECASE),
        "[NEXUS GUARD] Live broker operations are blocked. Invariant real_broker_calls == 0 must be preserved.",
    ),
    # 6. Production deploy commands without explicit executive override
    (
        re.compile(
            r"(\bterraform\s+apply\b.*(-auto-approve|\bprod|\bproduction)|\bkubectl\s+apply\b.*(\bprod|\bproduction)|\baws\s+ecs\s+update-service\b.*(\bprod|\bproduction)|\b(deploy_prod|deploy_production)\b)",
            re.IGNORECASE,
        ),
        "[NEXUS GUARD] Direct production deploy commands are blocked under Nexus generic directives.",
    ),
]


def evaluate_command(command_line: str) -> dict[str, str]:
    cmd = command_line.strip()
    for pattern, reason in PROHIBITED_PATTERNS:
        if pattern.search(cmd):
            return {
                "decision": "deny",
                "reason": reason,
            }
    return {
        "decision": "allow",
        "reason": "Standard safe development operation.",
    }


def main() -> None:
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
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
