"""
Pre-Tool Execution Guardrail for Antigravity (Meridian Nexus Governance)

Enforces non-negotiable safety policies:
1. Git Force Push: Blocks git push --force, -f, --force-with-lease
2. Git Direct Push to Main: Blocks direct push targeting main branch
3. Git Remote Branch Deletion: Blocks remote deletion of main branch
4. Git Destructive Reset: Blocks git reset --hard across all target variations
5. Git Destructive Clean: Blocks git clean with force flags (-f, -fdx, --force)
6. Git Protected Branch Deletion: Blocks local branch deletion of main
7. Live Broker Activation: Blocks flags/variables triggering real broker trading
8. Unauthorized Production Deploy: Blocks terraform apply, kubectl apply, aws ecs update-service across global flags
9. Fail-Closed Payload Guard: Blocks empty, malformed, or structurally invalid tool payloads
10. Everyday Development Operations: Transparently allows safe testing, feature branch push, and non-command tools.
"""
from __future__ import annotations

import json
import re
import sys

PROHIBITED_PATTERNS = [
    # 1. Force push
    (
        re.compile(
            r"\bgit\b.*?\bpush\b.*(\s--force\b|\s-f\b|\s--force-with-lease\b)",
            re.IGNORECASE,
        ),
        "[NEXUS GUARD] Force push is strictly prohibited by Nexus Directive 000 Git Governance.",
    ),
    # 2. Remote deletion of main
    (
        re.compile(
            r"\bgit\b.*?\bpush\b.*?(?:--delete\b.*?\bmain\b|\s-d\b.*?\bmain\b|\s:main\b)",
            re.IGNORECASE,
        ),
        "[NEXUS GUARD] Remote deletion of main branch is strictly prohibited.",
    ),
    # 3. Direct push to main
    (
        re.compile(
            r"\bgit\b.*?\bpush\b.*?(?:\smain\b|\S+:main\b)",
            re.IGNORECASE,
        ),
        "[NEXUS GUARD] Direct push to main branch is strictly prohibited. Work must proceed via dedicated directive branches.",
    ),
    # 4. Destructive git reset --hard
    (
        re.compile(r"\bgit\b.*?\breset\b.*?\s--hard\b", re.IGNORECASE),
        "[NEXUS GUARD] Destructive git reset --hard is strictly prohibited by Nexus Directive 000 Git Governance.",
    ),
    # 5. Destructive git clean
    (
        re.compile(
            r"\bgit\b.*?\bclean\b.*?(?:-[a-zA-Z]*f[a-zA-Z]*\b|--force\b)",
            re.IGNORECASE,
        ),
        "[NEXUS GUARD] Destructive git clean is blocked. Working tree must be preserved.",
    ),
    # 6. Local branch deletion of main
    (
        re.compile(r"\bgit\b.*?\bbranch\b.*?\s-(?:d|D)\s+main\b", re.IGNORECASE),
        "[NEXUS GUARD] Deletion of main branch is strictly prohibited.",
    ),
    # 7. Live broker command line triggers
    (
        re.compile(
            r"(--live-broker\b|\bLIVE_BROKER=1\b|\bCEDRO_PRODUCTION=1\b|--broker-live\b|\bMT5_LIVE=1\b)",
            re.IGNORECASE,
        ),
        "[NEXUS GUARD] Live broker operations are blocked. Invariant real_broker_calls == 0 must be preserved.",
    ),
    # 8. Unauthorized production deploy (order-independent flags)
    (
        re.compile(
            r"(\bterraform\b.*?\bapply\b.*(-auto-approve|\bprod|\bproduction)|\bterraform\b.*?\b(prod|\bproduction)\b.*?\bapply\b|\bkubectl\b.*?\bapply\b.*?\b(prod|production)\b|\bkubectl\b.*?\b(prod|production)\b.*?\bapply\b|\baws\b.*?\becs\b.*?\bupdate-service\b.*?\b(prod|production)\b|\baws\b.*?\b(prod|production)\b.*?\becs\b.*?\bupdate-service\b|\b(deploy_prod|deploy_production)\b)",
            re.IGNORECASE,
        ),
        "[NEXUS GUARD] Direct production deploy commands are blocked under Nexus generic directives.",
    ),
]


def evaluate_command(command_line: str) -> dict[str, str]:
    cmd = command_line.strip()
    if not cmd:
        return {
            "decision": "deny",
            "reason": "[NEXUS GUARD] Empty command string rejected.",
        }
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
        if not raw_input or not raw_input.strip():
            print(json.dumps({
                "decision": "deny",
                "reason": "[NEXUS GUARD] Empty input payload rejected. Fail-closed enforced.",
            }))
            return

        payload = json.loads(raw_input)
        if not isinstance(payload, dict):
            print(json.dumps({
                "decision": "deny",
                "reason": "[NEXUS GUARD] Payload must be a JSON object. Fail-closed enforced.",
            }))
            return

        tool_call = payload.get("toolCall")
        if not isinstance(tool_call, dict):
            print(json.dumps({
                "decision": "deny",
                "reason": "[NEXUS GUARD] Missing or invalid toolCall object. Fail-closed enforced.",
            }))
            return

        tool_name = tool_call.get("name", "")
        args = tool_call.get("args")

        if tool_name == "run_command":
            if not isinstance(args, dict):
                print(json.dumps({
                    "decision": "deny",
                    "reason": "[NEXUS GUARD] run_command missing args object. Fail-closed enforced.",
                }))
                return
            cmd_line = args.get("CommandLine")
            if not isinstance(cmd_line, str):
                print(json.dumps({
                    "decision": "deny",
                    "reason": "[NEXUS GUARD] run_command missing CommandLine argument. Fail-closed enforced.",
                }))
                return
            result = evaluate_command(cmd_line)
            print(json.dumps(result))
            return

        print(json.dumps({
            "decision": "allow",
            "reason": "Non-command tool allowed.",
        }))
    except Exception as exc:
        print(json.dumps({
            "decision": "deny",
            "reason": f"[NEXUS GUARD] Hook error: {exc}",
        }))


if __name__ == "__main__":
    main()
