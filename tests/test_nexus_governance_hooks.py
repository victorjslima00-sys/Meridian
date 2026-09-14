"""
Automated validation of Nexus Governance Hooks
Verifies deterministic guardrails across all 7 declared categories:
1. Force Push (Positive & Negative)
2. Destructive Git Reset --hard (Positive & Negative)
3. Destructive Git Clean (Positive & Negative)
4. Protected Branch Deletion (Positive & Negative)
5. Live Broker Activation (Positive & Negative)
6. Production Deploy (Positive & Negative)
7. Everyday Development Operations (Allowed)
"""
import json
from pathlib import Path
import subprocess
import sys

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
        "conversationId": "test-nexus-000a"
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
    # 1. Force Push
    def test_git_force_push_is_denied(self):
        forbidden = [
            "git push --force origin main",
            "git push -f origin main",
            "git push origin main --force-with-lease",
            "git push -f origin nexus/000-governance-bootstrap",
        ]
        for cmd in forbidden:
            res = run_guard(cmd)
            assert res["decision"] == "deny", f"Should have denied: {cmd}"
            assert "Force push is strictly prohibited" in res["reason"]

    def test_git_normal_push_is_allowed(self):
        allowed = [
            "git push origin nexus/000-governance-bootstrap",
            "git push -u origin feature-branch",
            "git push",
        ]
        for cmd in allowed:
            res = run_guard(cmd)
            assert res["decision"] == "allow", f"Failed on safe push: {cmd}"

    # 2. Destructive Git Reset --hard
    def test_git_reset_hard_is_denied(self):
        forbidden = [
            "git reset --hard",
            "git reset --hard HEAD",
            "git reset --hard HEAD~1",
            "git reset --hard origin/main",
            "git reset -q --hard",
            "git -C work/Meridian reset --hard HEAD~2",
        ]
        for cmd in forbidden:
            res = run_guard(cmd)
            assert res["decision"] == "deny", f"Should have denied reset --hard: {cmd}"
            assert "Destructive git reset --hard is strictly prohibited" in res["reason"]

    def test_git_reset_soft_mixed_is_allowed(self):
        allowed = [
            "git reset HEAD tests/test_temp.py",
            "git reset --soft HEAD~1",
            "git reset --mixed HEAD~1",
            "git reset",
        ]
        for cmd in allowed:
            res = run_guard(cmd)
            assert res["decision"] == "allow", f"Failed on safe reset: {cmd}"

    # 3. Destructive Git Clean
    def test_git_clean_force_is_denied(self):
        forbidden = [
            "git clean -fdx",
            "git clean -f",
            "git clean -df",
            "git clean -fx",
        ]
        for cmd in forbidden:
            res = run_guard(cmd)
            assert res["decision"] == "deny", f"Should have denied clean: {cmd}"
            assert "Destructive git clean is blocked" in res["reason"]

    def test_git_clean_dry_run_is_allowed(self):
        allowed = [
            "git clean -n",
            "git clean --dry-run",
        ]
        for cmd in allowed:
            res = run_guard(cmd)
            assert res["decision"] == "allow", f"Failed on safe dry-run clean: {cmd}"

    # 4. Protected Branch Deletion
    def test_git_branch_deletion_of_main_is_denied(self):
        forbidden = [
            "git branch -D main",
            "git branch -d main",
        ]
        for cmd in forbidden:
            res = run_guard(cmd)
            assert res["decision"] == "deny", f"Should have denied branch deletion of main: {cmd}"
            assert "Deletion of main branch is strictly prohibited" in res["reason"]

    def test_git_branch_safe_operations_allowed(self):
        allowed = [
            "git branch",
            "git branch -a",
            "git branch -D temp-scratch-branch",
            "git checkout -b new-branch",
        ]
        for cmd in allowed:
            res = run_guard(cmd)
            assert res["decision"] == "allow", f"Failed on safe branch command: {cmd}"

    # 5. Live Broker Activation
    def test_live_broker_activation_is_denied(self):
        forbidden = [
            "python scripts/run_paper_session.py --live-broker",
            "LIVE_BROKER=1 python run.py",
            "CEDRO_PRODUCTION=1 python start.py",
            "python bot.py --broker-live",
            "MT5_LIVE=1 python bot.py",
        ]
        for cmd in forbidden:
            res = run_guard(cmd)
            assert res["decision"] == "deny", f"Should have denied live broker: {cmd}"
            assert "real_broker_calls == 0" in res["reason"]

    def test_paper_trading_execution_is_allowed(self):
        allowed = [
            "python scripts/run_paper_session.py --ticks 10",
            "python scripts/run_coordinator.py --dry-run",
            "python scripts/evaluate_research_models.py",
        ]
        for cmd in allowed:
            res = run_guard(cmd)
            assert res["decision"] == "allow", f"Failed on paper trading command: {cmd}"

    # 6. Production Deploy
    def test_production_deploy_is_denied(self):
        forbidden = [
            "terraform apply -auto-approve",
            "terraform apply -var-file=prod.tfvars",
            "kubectl apply -f k8s/production/",
            "kubectl apply -f k8s/prod.yaml",
            "aws ecs update-service --cluster prod-cluster --service web",
            "python scripts/deploy_production.py",
            "python deploy_prod.py",
        ]
        for cmd in forbidden:
            res = run_guard(cmd)
            assert res["decision"] == "deny", f"Should have denied production deploy: {cmd}"
            assert "Direct production deploy commands are blocked" in res["reason"]

    def test_safe_infra_inspection_is_allowed(self):
        allowed = [
            "terraform plan",
            "terraform init",
            "kubectl get pods",
            "kubectl describe service",
            "aws s3 ls",
        ]
        for cmd in allowed:
            res = run_guard(cmd)
            assert res["decision"] == "allow", f"Failed on safe infra inspection: {cmd}"

    # 7. Everyday Development Operations
    def test_safe_development_commands_are_allowed(self):
        safe_commands = [
            "pytest tests/ -v",
            "git status",
            "git add .",
            "git commit -m 'chore: test'",
            "npm test",
            "node frontend/honesty.test.mjs",
            "flake8 .",
            "python -m pip install -r requirements-dev.txt",
        ]
        for cmd in safe_commands:
            res = run_guard(cmd)
            assert res["decision"] == "allow", f"Failed on safe development command: {cmd}"
