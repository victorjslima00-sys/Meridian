"""
Automated validation of Nexus Governance Hooks
Verifies deterministic guardrails:
1. Safe commands allowed
2. Force pushes and destructive git commands denied
3. Live broker and direct production deploy commands denied
"""
import pytest
import subprocess
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = REPO_ROOT / ".agents" / "scripts" / "pre_tool_guard.py"

def run_guard(command_line: str) -> dict:
    payload = {
        "toolCall": {
            "name": "run_command",
            "args": {
                "CommandLine": command_line
            }
        },
        "stepIdx": 1,
        "conversationId": "test-nexus-000"
    }
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True
    )
    return json.loads(proc.stdout)

class TestNexusGovernanceHooks:
    def test_safe_commands_are_allowed(self):
        safe_commands = [
            "pytest tests/ -v",
            "git status",
            "git add .",
            "git commit -m 'chore: test'",
            "git push origin nexus/000-governance-bootstrap",
            "python scripts/run_paper_session.py",
            "npm test",
            "node frontend/honesty.test.mjs"
        ]
        for cmd in safe_commands:
            res = run_guard(cmd)
            assert res["decision"] == "allow", f"Failed on safe command: {cmd}"

    def test_git_force_push_is_denied(self):
        forbidden = [
            "git push --force origin main",
            "git push -f origin main",
            "git push origin main --force-with-lease"
        ]
        for cmd in forbidden:
            res = run_guard(cmd)
            assert res["decision"] == "deny", f"Should have denied: {cmd}"
            assert "Force push is strictly prohibited" in res["reason"]

    def test_destructive_git_operations_are_denied(self):
        forbidden = [
            "git clean -fdx",
            "git branch -D main"
        ]
        for cmd in forbidden:
            res = run_guard(cmd)
            assert res["decision"] == "deny", f"Should have denied: {cmd}"

    def test_live_broker_activation_is_denied(self):
        forbidden = [
            "python scripts/run_paper_session.py --live-broker",
            "LIVE_BROKER=1 python run.py"
        ]
        for cmd in forbidden:
            res = run_guard(cmd)
            assert res["decision"] == "deny", f"Should have denied: {cmd}"
            assert "real_broker_calls == 0" in res["reason"]
