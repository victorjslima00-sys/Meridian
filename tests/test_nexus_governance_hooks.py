"""
Automated validation of Nexus Governance Hooks (NEXUS-000C)
Verifies deterministic guardrails across all declared categories:
1. Git Force Push (Positive & Negative, including +refspec)
2. Git Direct Push to Main (Positive & Negative, including all refs/heads/main variants and global flags)
3. Git Remote Branch Deletion (Positive & Negative, including :refs/heads/main, --delete, -d)
4. Git Destructive Reset --hard (Positive & Negative)
5. Git Destructive Clean (Positive & Negative)
6. Git Protected Branch Deletion (Positive & Negative, including refs/heads/main)
7. Live Broker Activation (Positive & Negative)
8. Unauthorized Production Deploy (Positive & Negative, including global flags)
9. Fail-Closed Payload Guard (Positive & Negative)
10. Everyday Development Operations (Allowed)
11. Secret File Guard — View File (force_ask on secrets, allow on .env.example)
12. Secret File Guard — Write & Replace File (deny on secrets, allow on .env.example)
13. Shell Access to Secrets Guard (deny on .env/keys, allow on .env.example)
14. End-to-End Hook Invocations (Working directory resolution & dry-run command inspection)
"""
import json
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = REPO_ROOT / ".agents" / "scripts" / "pre_tool_guard.py"
ROOT_BRIDGE_SCRIPT = REPO_ROOT / "scripts" / "pre_tool_guard.py"


def run_raw_payload(payload_str: str, cwd: Path | None = None) -> dict:
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=payload_str,
        text=True,
        capture_output=True,
        check=True,
        cwd=cwd or REPO_ROOT
    )
    return json.loads(proc.stdout)


def run_guard(command_line: str) -> dict:
    payload = {
        "toolCall": {
            "name": "run_command",
            "args": {
                "CommandLine": command_line
            }
        },
        "stepIdx": 1,
        "conversationId": "test-nexus-000c"
    }
    return run_raw_payload(json.dumps(payload))


def run_tool_guard(tool_name: str, args: dict) -> dict:
    payload = {
        "toolCall": {
            "name": tool_name,
            "args": args
        },
        "stepIdx": 1,
        "conversationId": "test-nexus-000c"
    }
    return run_raw_payload(json.dumps(payload))


class TestNexusGovernanceHooks:
    # 1. Force Push
    def test_git_force_push_is_denied(self):
        forbidden = [
            "git push --force origin main",
            "git push -f origin main",
            "git push origin main --force-with-lease",
            "git push --force-if-includes origin main",
            "git push -f origin nexus/000-governance-bootstrap",
            "git push --force origin feature-test",
            "git push origin +HEAD:main",
            "git push origin +HEAD:refs/heads/main",
            "git push origin +main",
            "git push origin +refs/heads/main",
            "git push origin +feature-branch",
        ]
        for cmd in forbidden:
            res = run_guard(cmd)
            assert res["decision"] == "deny", f"Should have denied force push: {cmd}"
            assert "Force push" in res["reason"]

    def test_git_normal_push_is_allowed(self):
        allowed = [
            "git push origin nexus/000-governance-bootstrap",
            "git push -u origin feature-branch",
            "git push origin fix/broker-parser",
            "git push origin HEAD:nexus/feature-branch",
            "git push origin HEAD:refs/heads/feature-branch",
            "git push origin feature:refs/heads/feature",
        ]
        for cmd in allowed:
            res = run_guard(cmd)
            assert res["decision"] == "allow", f"Failed on safe push: {cmd}"

    # 2. Direct Push to Main (Section 5 adversarial ref equivalences)
    def test_git_direct_push_to_main_is_denied(self):
        forbidden = [
            "git push origin main",
            "git push upstream main",
            "git push origin HEAD:main",
            "git push origin feature:main",
            "git push origin HEAD:refs/heads/main",
            "git push origin feature:refs/heads/main",
            "git push origin refs/heads/main",
            "git -C work/Meridian push origin HEAD:main",
            "git -C work/Meridian push origin HEAD:refs/heads/main",
            "git --git-dir=.git push origin refs/heads/main",
            "git --no-pager push origin HEAD:main",
            "git -c user.name=test push origin feature:refs/heads/main",
        ]
        for cmd in forbidden:
            res = run_guard(cmd)
            assert res["decision"] == "deny", f"Should have denied direct push to main: {cmd}"
            assert "Direct push to main branch is strictly prohibited" in res["reason"]

    def test_git_push_to_feature_branch_is_allowed(self):
        allowed = [
            "git push origin nexus/000-governance-bootstrap",
            "git push origin HEAD:nexus/feature-branch",
            "git push origin HEAD:refs/heads/feature-branch",
            "git push origin feature:refs/heads/feature-123",
        ]
        for cmd in allowed:
            res = run_guard(cmd)
            assert res["decision"] == "allow", f"Failed on safe branch push: {cmd}"

    # 3. Remote Branch Deletion of Main (Section 5 adversarial ref equivalences)
    def test_git_remote_deletion_of_main_is_denied(self):
        forbidden = [
            "git push origin --delete main",
            "git push origin :main",
            "git push origin :refs/heads/main",
            "git push origin :+main",
            "git push origin :+refs/heads/main",
            "git push -d origin main",
            "git push origin -d main",
            "git push upstream --delete main",
            "git push origin --delete refs/heads/main",
            "git push origin -d refs/heads/main",
            "git push --delete origin refs/heads/main",
            "git push -d origin refs/heads/main",
            "git -C repo push origin :main",
            "git -C repo push origin :refs/heads/main",
        ]
        for cmd in forbidden:
            res = run_guard(cmd)
            assert res["decision"] == "deny", f"Should have denied remote delete of main: {cmd}"
            assert "Remote deletion of main branch is strictly prohibited" in res["reason"]

    def test_git_remote_deletion_of_scratch_branch_is_allowed(self):
        allowed = [
            "git push origin --delete scratch-branch",
            "git push origin :temp-test-branch",
            "git push origin :refs/heads/temp-test-branch",
            "git push origin --delete refs/heads/scratch-branch",
            "git push origin -d refs/heads/scratch-branch",
        ]
        for cmd in allowed:
            res = run_guard(cmd)
            assert res["decision"] == "allow", f"Failed on safe remote branch delete: {cmd}"

    # 4. Destructive Git Reset --hard
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

    # 5. Destructive Git Clean
    def test_git_clean_force_is_denied(self):
        forbidden = [
            "git clean -fdx",
            "git clean -f",
            "git clean -df",
            "git clean -fx",
            "git clean -xdf",
            "git clean --force",
            "git clean --force -d -x",
        ]
        for cmd in forbidden:
            res = run_guard(cmd)
            assert res["decision"] == "deny", f"Should have denied clean: {cmd}"
            assert "Destructive git clean is blocked" in res["reason"]

    def test_git_clean_dry_run_is_allowed(self):
        allowed = [
            "git clean -n",
            "git clean -n -d",
            "git clean --dry-run",
        ]
        for cmd in allowed:
            res = run_guard(cmd)
            assert res["decision"] == "allow", f"Failed on safe dry-run clean: {cmd}"

    # 6. Local Protected Branch Deletion
    def test_git_branch_deletion_of_main_is_denied(self):
        forbidden = [
            "git branch -D main",
            "git branch -d main",
            "git branch -D refs/heads/main",
            "git branch -d refs/heads/main",
            "git branch --delete main",
            "git branch --delete refs/heads/main",
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
            "git branch -d temp-scratch-branch",
            "git checkout -b new-branch",
        ]
        for cmd in allowed:
            res = run_guard(cmd)
            assert res["decision"] == "allow", f"Failed on safe branch command: {cmd}"

    # 7. Live Broker Activation
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

    # 8. Production Deploy (including global flags)
    def test_production_deploy_is_denied(self):
        forbidden = [
            "terraform apply -auto-approve",
            "terraform -chdir=infra apply -auto-approve",
            "terraform apply -var-file=prod.tfvars",
            "terraform -chdir=prod apply",
            "kubectl apply -f k8s/production/",
            "kubectl apply -f k8s/prod.yaml",
            "kubectl --context=prod apply -f manifest.yaml",
            "kubectl -n production apply -f svc.yaml",
            "aws ecs update-service --cluster prod-cluster --service web",
            "aws --profile=prod ecs update-service --service web",
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
            "terraform -chdir=infra plan",
            "terraform init",
            "kubectl get pods",
            "kubectl --context=prod get pods",
            "kubectl describe service",
            "aws s3 ls",
            "aws --profile=prod s3 ls",
        ]
        for cmd in allowed:
            res = run_guard(cmd)
            assert res["decision"] == "allow", f"Failed on safe infra inspection: {cmd}"

    # 9. Fail-Closed Payload Guard
    def test_invalid_or_empty_payload_is_denied(self):
        invalid_payloads = [
            "",
            "   ",
            "not-json-content",
            "[]",
            json.dumps({"unrecognized": True}),
            json.dumps({"toolCall": "string-not-dict"}),
            json.dumps({"toolCall": {"name": "run_command"}}),
            json.dumps({"toolCall": {"name": "run_command", "args": {}}}),
            json.dumps({"toolCall": {"name": "run_command", "args": {"CommandLine": ""}}}),
        ]
        for payload in invalid_payloads:
            res = run_raw_payload(payload)
            assert res["decision"] == "deny", f"Should have denied payload: {payload}"

    def test_non_command_tools_are_allowed(self):
        valid_tools = [
            {"toolCall": {"name": "grep_search", "args": {"Query": "test"}}},
            {"toolCall": {"name": "find_by_name", "args": {"Pattern": "*.py"}}},
            {"toolCall": {"name": "list_dir", "args": {"DirectoryPath": "src"}}},
        ]
        for payload in valid_tools:
            res = run_raw_payload(json.dumps(payload))
            assert res["decision"] == "allow", f"Failed on legitimate tool: {payload}"
            assert res["reason"] == "Non-command tool allowed."

    # 10. Everyday Development Operations
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

    # 11. Secret File Guard — view_file (Section 6)
    def test_secret_file_view_requires_force_ask(self):
        sensitive_paths = [
            ".env",
            ".env.local",
            ".env.production",
            ".env.staging",
            "C:/app/Meridian/.env",
            "deploy_key.pem",
            "~/.ssh/id_rsa",
            "~/.ssh/id_ed25519",
            "infra/secrets/credentials.json",
            "certs/server.key",
            "config/private_key.pem",
        ]
        for path in sensitive_paths:
            res = run_tool_guard("view_file", {"AbsolutePath": path})
            assert res["decision"] == "force_ask", f"Expected force_ask for viewing {path}"
            assert "Reading sensitive credential file" in res["reason"]

    def test_env_example_view_is_allowed(self):
        example_paths = [
            ".env.example",
            "C:/Users/BIRTUS JANIO/Documents/Codex/2026-09-11/oque/work/Meridian/.env.example",
            "frontend/.env.example",
        ]
        for path in example_paths:
            res = run_tool_guard("view_file", {"AbsolutePath": path})
            assert res["decision"] == "allow", f"Expected allow for viewing {path}"

    def test_non_secret_file_view_is_allowed(self):
        safe_paths = [
            "test_api_key.py",
            "key_metrics.py",
            "keyboard.ts",
            "trading_bot/core/clock.py",
            "README.md",
            "tests/test_deploy_governance.py",
        ]
        for path in safe_paths:
            res = run_tool_guard("view_file", {"AbsolutePath": path})
            assert res["decision"] == "allow", f"Expected allow for viewing safe file {path}"

    # 12. Secret File Guard — write_to_file & replace_file_content (Section 6)
    def test_secret_file_write_is_denied(self):
        sensitive_targets = [
            ".env",
            ".env.production",
            ".env.local",
            "deploy_key.pem",
            "id_rsa",
            "id_ed25519",
            "secrets/vault.json",
            "certs/private_key.pem",
        ]
        for tool_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
            for target in sensitive_targets:
                res = run_tool_guard(tool_name, {"TargetFile": target})
                assert res["decision"] == "deny", f"Expected deny for {tool_name} on {target}"
                assert "Writing or modifying sensitive credential file" in res["reason"]

    def test_env_example_write_is_allowed(self):
        example_targets = [
            ".env.example",
            "frontend/.env.example",
        ]
        for tool_name in ("write_to_file", "replace_file_content"):
            for target in example_targets:
                res = run_tool_guard(tool_name, {"TargetFile": target})
                assert res["decision"] == "allow", f"Expected allow for {tool_name} on {target}"

    def test_non_secret_file_write_is_allowed(self):
        safe_targets = [
            "src/models.py",
            "tests/test_key_manager.py",
            "frontend/src/App.tsx",
        ]
        for tool_name in ("write_to_file", "replace_file_content"):
            for target in safe_targets:
                res = run_tool_guard(tool_name, {"TargetFile": target})
                assert res["decision"] == "allow", f"Expected allow for {tool_name} on {target}"

    # 13. Direct Shell Secret Access Guard (Section 6)
    def test_shell_access_to_secrets_is_denied(self):
        forbidden_shell = [
            "cat .env",
            "type .env",
            "Get-Content .env",
            "cat .env.production",
            "type deploy_key.pem",
            "cat ~/.ssh/id_rsa",
            "rm .env",
            "echo SECRET=1 > .env",
        ]
        for cmd in forbidden_shell:
            res = run_guard(cmd)
            assert res["decision"] == "deny", f"Expected deny for shell access to secret: {cmd}"
            assert "Direct shell access to sensitive credentials" in res["reason"]

    def test_shell_access_to_env_example_is_allowed(self):
        allowed_shell = [
            "cat .env.example",
            "type .env.example",
        ]
        for cmd in allowed_shell:
            res = run_guard(cmd)
            assert res["decision"] == "allow", f"Expected allow for shell access to example: {cmd}"

    # 14. End-to-End Hook Invocations (Section 4 & 7)
    def test_e2e_hook_execution_from_agents_dir(self):
        payload = json.dumps({
            "toolCall": {"name": "run_command", "args": {"CommandLine": "git status"}}
        })
        agents_dir = REPO_ROOT / ".agents"
        res = run_raw_payload(payload, cwd=agents_dir)
        assert res["decision"] == "allow"

    def test_e2e_hook_execution_from_repo_root(self):
        payload = json.dumps({
            "toolCall": {"name": "run_command", "args": {"CommandLine": "git status"}}
        })
        res = run_raw_payload(payload, cwd=REPO_ROOT)
        assert res["decision"] == "allow"

    def test_e2e_dry_run_push_to_main_is_denied(self):
        dry_run_commands = [
            "git push --dry-run origin HEAD:main",
            "git push --dry-run --force origin HEAD:main",
            "git push --dry-run origin HEAD:refs/heads/main",
            "git push --dry-run origin :refs/heads/main",
        ]
        for cmd in dry_run_commands:
            res = run_guard(cmd)
            assert res["decision"] == "deny", f"Expected deny for dry-run push to main: {cmd}"
