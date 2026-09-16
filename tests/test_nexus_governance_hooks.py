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
15. ARGUS Institutional Registry & Governance Contract (NEXUS-004-R2-FORGE-A)
"""
import json
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = REPO_ROOT / ".agents" / "scripts" / "pre_tool_guard.py"
ROOT_BRIDGE_SCRIPT = REPO_ROOT / "scripts" / "pre_tool_guard.py"

# NEXUS-004-R2-FORGE-A — canonical ARGUS governance registry surface.
REGISTRY_PATH = REPO_ROOT / ".agents" / "registry" / "argus.md"
GITIGNORE_PATH = REPO_ROOT / ".gitignore"

# Responsibilities required by the registry contract (NEXUS-004-R2-FORGE-A §6).
ARGUS_RESPONSIBILITIES = (
    "adversarial_code_review",
    "execution_path_tracing",
    "authority_bypass_detection",
    "financial_mutation_audit",
    "regression_discovery",
    "test_quality_review",
    "provenance_verification",
    "stale_data_analysis",
    "nan_inf_analysis",
    "tamper_analysis",
    "concurrency_analysis",
    "replay_analysis",
    "restart_recovery_analysis",
    "implementation_report_verification",
)

# Authority flags that MUST be declared false for the verification role.
ARGUS_FALSE_AUTHORITY_FLAGS = (
    "technical_acceptance",
    "merge_authority",
    "deployment_authority",
    "release_authority",
    "capital_authority",
    "dataset_approval_authority",
    "risk_override_authority",
    "live_broker_authority",
    "sentinel_bypass_authority",
)

REGISTRY_KEY_RE = re.compile(r"^([a-z][a-z0-9_]*):[ \t]*(.+?)[ \t]*$")


def find_git_executable() -> str | None:
    """Locate a usable git binary from PATH or a generic environment override.

    Deliberately free of machine/user-specific absolute paths: when git cannot
    be discovered the caller must skip the empirical layer instead of guessing
    at a hardcoded location that only exists on one workstation.
    """
    override = os.environ.get("GIT_EXECUTABLE")
    if override and Path(override).is_file():
        return override
    return shutil.which("git")


def load_registry_fields() -> dict[str, list[str]]:
    """Extract every `key: value` contract pair from the ARGUS registry entry.

    The scan is semantic, not positional: Markdown heading depth, bullet style
    and surrounding prose are ignored, so assertions target the governance
    contract instead of paragraph formatting. All occurrences of a key are
    preserved so a duplicated or conflicting line cannot silently win.
    """
    assert REGISTRY_PATH.is_file(), f"ARGUS registry entry is missing: {REGISTRY_PATH}"
    fields: dict[str, list[str]] = {}
    for raw_line in REGISTRY_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("- "):
            line = line[2:].strip()
        match = REGISTRY_KEY_RE.match(line)
        if match:
            fields.setdefault(match.group(1), []).append(match.group(2))
    return fields


def single_registry_field(fields: dict[str, list[str]], key: str) -> str:
    """Return the unique value for `key`, failing closed on absence/duplication."""
    values = fields.get(key)
    assert values, f"ARGUS registry must declare `{key}:` (found none)"
    assert len(values) == 1, f"ARGUS registry must declare `{key}:` once, found {values}"
    return values[0]


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
            "git push origin refs/heads/maintenance",
            "git push origin refs/heads/main-feature",
            "git push origin refs/heads/mainline",
            "git push origin feature:refs/heads/maintenance",
        ]
        for cmd in allowed:
            res = run_guard(cmd)
            assert res["decision"] == "allow", f"Failed on safe branch push: {cmd}"

    def test_blanket_push_and_mirror_are_denied(self):
        forbidden = [
            "git push origin --all",
            "git push --all",
            "git push origin --mirror",
            "git push --mirror",
            "git push origin :",
        ]
        for cmd in forbidden:
            res = run_guard(cmd)
            assert res["decision"] == "deny", f"Should have denied blanket push: {cmd}"
            assert "strictly prohibited" in res["reason"]

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
            "git branch -d refs/heads/maintenance",
            "git branch -D refs/heads/main-feature",
            "git checkout -b new-branch",
        ]
        for cmd in allowed:
            res = run_guard(cmd)
            assert res["decision"] == "allow", f"Failed on safe branch command: {cmd}"

    def test_git_branch_rename_and_update_ref_main_are_denied(self):
        forbidden = [
            "git branch -m main other",
            "git branch -M main other",
            "git branch -m other main",
            "git branch -M other main",
            "git branch --move main other",
            "git update-ref refs/heads/main HEAD",
            "git update-ref -d refs/heads/main",
        ]
        for cmd in forbidden:
            res = run_guard(cmd)
            assert res["decision"] == "deny", f"Should have denied ref modification: {cmd}"

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

    # 11. Secret File Guard — view_file & read_file (Section 6)
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
            "config/credentials.json",
            "client_secret.json",
            "~/.aws/credentials",
            "secrets.json",
            "vault.json",
            "certs/server.key",
            "config/private_key.pem",
        ]
        for tool_name in ("view_file", "read_file"):
            for path in sensitive_paths:
                res = run_tool_guard(tool_name, {"AbsolutePath": path})
                assert res["decision"] == "force_ask", f"Expected force_ask for {tool_name} on {path}"
                assert "Reading sensitive credential file" in res["reason"]

    def test_env_example_view_is_allowed(self):
        example_paths = [
            ".env.example",
            "C:/Users/BIRTUS JANIO/Documents/Codex/2026-09-11/oque/work/Meridian/.env.example",
            "frontend/.env.example",
        ]
        for tool_name in ("view_file", "read_file"):
            for path in example_paths:
                res = run_tool_guard(tool_name, {"AbsolutePath": path})
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
        for tool_name in ("view_file", "read_file"):
            for path in safe_paths:
                res = run_tool_guard(tool_name, {"AbsolutePath": path})
                assert res["decision"] == "allow", f"Expected allow for viewing safe file {path}"

    # 12. Secret File Guard — write_to_file, write_file & replace_file_content (Section 6)
    def test_secret_file_write_is_denied(self):
        sensitive_targets = [
            ".env",
            ".env.production",
            ".env.local",
            "deploy_key.pem",
            "id_rsa",
            "id_ed25519",
            "secrets/vault.json",
            "config/credentials.json",
            "client_secret.json",
            "~/.aws/credentials",
            "secrets.json",
            "certs/private_key.pem",
        ]
        for tool_name in ("write_to_file", "write_file", "replace_file_content", "multi_replace_file_content"):
            for target in sensitive_targets:
                res = run_tool_guard(tool_name, {"TargetFile": target})
                assert res["decision"] == "deny", f"Expected deny for {tool_name} on {target}"
                assert "Writing or modifying sensitive credential file" in res["reason"]

    def test_env_example_write_is_allowed(self):
        example_targets = [
            ".env.example",
            "frontend/.env.example",
        ]
        for tool_name in ("write_to_file", "write_file", "replace_file_content"):
            for target in example_targets:
                res = run_tool_guard(tool_name, {"TargetFile": target})
                assert res["decision"] == "allow", f"Expected allow for {tool_name} on {target}"

    def test_non_secret_file_write_is_allowed(self):
        safe_targets = [
            "src/models.py",
            "tests/test_key_manager.py",
            "frontend/src/App.tsx",
        ]
        for tool_name in ("write_to_file", "write_file", "replace_file_content"):
            for target in safe_targets:
                res = run_tool_guard(tool_name, {"TargetFile": target})
                assert res["decision"] == "allow", f"Expected allow for {tool_name} on {target}"

    # 13. Direct Shell Secret Access Guard (Section 6)
    def test_shell_access_to_secrets_is_denied(self):
        forbidden_shell = [
            "cat .env",
            "type .env",
            "Get-Content .env",
            "gc .env",
            "more .env",
            "less .env",
            "grep KEY .env",
            "rg SECRET .env",
            "findstr KEY .env",
            "cat .env.production",
            "type deploy_key.pem",
            "cat ~/.ssh/id_rsa",
            "rm .env",
            "echo SECRET=1 > .env",
            "python -c \"import os; open('.env').read()\"",
            "powershell -Command \"Get-Content .env\"",
            "powershell Get-Content .env.local",
        ]
        for cmd in forbidden_shell:
            res = run_guard(cmd)
            assert res["decision"] == "deny", f"Expected deny for shell access to secret: {cmd}"
            assert "sensitive credentials" in res["reason"]

    def test_shell_access_to_env_example_is_allowed(self):
        allowed_shell = [
            "cat .env.example",
            "type .env.example",
            "python -c \"open('.env.example').read()\"",
            "powershell Get-Content .env.example",
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

    # 15. Commit SHA Traceability Protocol (NEXUS-000D Section 1)
    def test_commit_sha_traceability_protocol(self):
        """Ensure git rev-parse HEAD yields a 40-character hex SHA without reconstruction."""
        import shutil
        git_exe = shutil.which("git")
        if not git_exe:
            for cand in [
                Path(r"C:\Users\BIRTUS JANIO\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"),
            ]:
                if cand.exists():
                    git_exe = str(cand)
                    break
        if git_exe:
            p = subprocess.run([git_exe, "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
            head_sha = p.stdout.strip()
            assert len(head_sha) == 40, f"Expected 40-char SHA, got: {head_sha}"
            assert all(c in "0123456789abcdefABCDEF" for c in head_sha)


class TestArgusGovernanceRegistry:
    """NEXUS-004-R2-FORGE-A — canonical ARGUS registry + tracking policy.

    Governance documentation is only enforceable if its contract is asserted
    deterministically: existence, versionability, canonical identity, zero
    authority escalation, self-review restriction and allowed outcomes.
    """

    # A. Canonical registry entry exists.
    def test_registry_entry_exists(self):
        assert REGISTRY_PATH.is_file(), f"Canonical ARGUS registry is missing: {REGISTRY_PATH}"
        assert REGISTRY_PATH.read_text(encoding="utf-8").strip(), "ARGUS registry must not be empty"

    # B. The ignore policy re-includes the registry (declared rule layer).
    def test_ignore_policy_reincludes_registry(self):
        lines = {line.strip() for line in GITIGNORE_PATH.read_text(encoding="utf-8").splitlines()}
        assert ".agents/*" in lines, "Baseline `.agents/*` ignore rule expected in .gitignore"
        assert "!.agents/registry/" in lines, ".gitignore must re-include .agents/registry/"
        assert ".agents/registry/*" in lines, ".gitignore must re-ignore registry siblings"
        assert "!.agents/registry/argus.md" in lines, ".gitignore must re-include the canonical entry"

    # B (empirical). git itself must agree the canonical entry is not ignored.
    def test_git_reports_registry_entry_as_trackable(self):
        git_exe = find_git_executable()
        if git_exe is None:
            pytest.skip("git executable unavailable; policy asserted from .gitignore text only")
        proc = subprocess.run(
            [git_exe, "check-ignore", "-q", ".agents/registry/argus.md"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert proc.returncode == 1, (
            "`git check-ignore .agents/registry/argus.md` must exit 1 (NOT ignored); "
            f"got exit {proc.returncode}. stdout={proc.stdout!r}"
        )

    # P2 (NEXUS-004-R2-FORGE-A-R1). Registry trackability must stay narrow: an
    # arbitrary sibling is ignored, so removing `.agents/registry/*` (which
    # would make the whole directory trackable again) fails this test.
    def test_registry_sibling_files_stay_ignored(self):
        git_exe = find_git_executable()
        if git_exe is None:
            pytest.skip("git executable unavailable")
        siblings = (
            ".agents/registry/argus_future_probe.txt",
            ".agents/registry/notes.md",
            ".agents/registry/argus.md.bak",
        )
        for probe in siblings:
            proc = subprocess.run(
                [git_exe, "check-ignore", "-q", probe],
                cwd=REPO_ROOT, capture_output=True, text=True,
            )
            assert proc.returncode == 0, (
                f"{probe} must stay ignored by the narrow `.agents/registry/*` policy; "
                f"got exit {proc.returncode}"
            )

    # The fix must not broadly unignore the .agents tree.
    def test_ephemeral_agents_paths_stay_ignored(self):
        git_exe = find_git_executable()
        if git_exe is None:
            pytest.skip("git executable unavailable")
        for probe in (
            ".agents/ephemeral_run_probe",
            ".agents/ephemeral_run_probe/log.txt",
            ".agents/ephemeral_argus_probe",
        ):
            proc = subprocess.run(
                [git_exe, "check-ignore", "-q", probe],
                cwd=REPO_ROOT, capture_output=True, text=True,
            )
            assert proc.returncode == 0, f"{probe} must remain ignored by the .agents/* policy"

    # C. Canonical name.
    def test_registry_declares_canonical_name(self):
        assert single_registry_field(load_registry_fields(), "canonical_name") == "ARGUS"

    # D. Runtime.
    def test_registry_declares_runtime(self):
        assert single_registry_field(load_registry_fields(), "runtime").lower() == "cline"

    # E. Role.
    def test_registry_declares_independent_verification_role(self):
        fields = load_registry_fields()
        role = single_registry_field(fields, "role").lower()
        assert "independent" in role and "verification" in role
        assert single_registry_field(fields, "class") == "verification_agent"

    # F. Reports to NEXUS.
    def test_registry_reports_to_nexus(self):
        assert single_registry_field(load_registry_fields(), "reports_to").lower() == "nexus"

    # G. Default access is READ_ONLY.
    def test_registry_default_access_is_read_only(self):
        assert single_registry_field(load_registry_fields(), "default_access").upper() == "READ_ONLY"

    # H-O. Authority flags must all be false.
    @pytest.mark.parametrize("flag", ARGUS_FALSE_AUTHORITY_FLAGS)
    def test_registry_authority_flag_is_false(self, flag):
        value = single_registry_field(load_registry_fields(), flag)
        assert value.lower() == "false", f"ARGUS `{flag}:` must be false, found {value!r}"

    # §6 permission matrix: read-only inspection granted, writes NEXUS-gated.
    @pytest.mark.parametrize("permission", (
        "inspect_repository",
        "inspect_git_history",
        "run_non_destructive_tests",
        "run_static_analysis",
    ))
    def test_registry_read_only_permissions_are_granted(self, permission):
        assert single_registry_field(load_registry_fields(), permission).lower() == "true"

    @pytest.mark.parametrize("permission", ("modify_code", "modify_tests"))
    def test_registry_write_permissions_require_nexus(self, permission):
        value = single_registry_field(load_registry_fields(), permission)
        assert value == "explicit_nexus_authorization_only", f"`{permission}:` found {value!r}"

    # P. Self-review restriction.
    def test_registry_contains_self_review_restriction(self):
        fields = load_registry_fields()
        assert single_registry_field(fields, "author_is_sole_independent_reviewer").lower() == "false"
        assert single_registry_field(fields, "self_review_authorized").lower() == "false"
        normalized = " ".join(REGISTRY_PATH.read_text(encoding="utf-8").split()).lower()
        assert "author != sole independent reviewer" in normalized

    # Q. Allowed review outcomes.
    def test_registry_contains_allowed_review_outcomes(self):
        text = REGISTRY_PATH.read_text(encoding="utf-8")
        for outcome in ("READY_FOR_NEXUS_REVIEW", "CORRECTION_REQUIRED", "UNVERIFIED"):
            assert outcome in text, f"Allowed review outcome missing from registry: {outcome}"

    def test_registry_reserves_final_acceptance_to_nexus(self):
        fields = load_registry_fields()
        assert single_registry_field(fields, "final_technical_acceptance_authority").lower() == "nexus"
        text = REGISTRY_PATH.read_text(encoding="utf-8")
        for reserved in ("NEXUS_ACCEPTED", "RELEASE_APPROVED", "LIVE_APPROVED"):
            assert reserved in text, f"Registry must list the reserved verdict: {reserved}"

    # §8 role identity must survive a model swap.
    def test_registry_identity_is_independent_of_llm(self):
        value = single_registry_field(load_registry_fields(), "institutional_identity_independent_of_llm")
        assert value.lower() == "true"

    # §6 required responsibility coverage.
    def test_registry_lists_required_responsibilities(self):
        text = REGISTRY_PATH.read_text(encoding="utf-8")
        missing = [item for item in ARGUS_RESPONSIBILITIES if item not in text]
        assert missing == [], f"Registry is missing required responsibilities: {missing}"

    # Contract keys must be unambiguous (no duplicated/conflicting declarations).
    def test_registry_contract_keys_are_unique(self):
        duplicated = {key: vals for key, vals in load_registry_fields().items() if len(vals) > 1}
        assert duplicated == {}, f"Ambiguous duplicated registry contract keys: {duplicated}"
