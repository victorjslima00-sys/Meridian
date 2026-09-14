"""
Automated validation of Deployment Governance (NEXUS-000D)
Enforces:
1. CI VERDE != AUTORIZACAO DE PRODUCAO (CI is necessary prerequisite, not authorizer)
2. No script injection via workflow inputs (inputs transported strictly via env:)
3. Closed-choice confirmation (default CANCEL)
4. Same-SHA Main CI prerequisite deterministically verified (head_branch == main, event == push, fail-closed)
5. Separation of Executive Authorization (Astra audit ref) and Technical Directive (Nexus technical ref)
6. Victor required human reviewer gate via GitHub Environment
7. Minimal permissions (contents: read, actions: read — zero write)
8. Deploy branch restricted exclusively to main
9. All 8 required secrets validated exhaustively before any SSH connection
10. Pinned SSH host authenticity (SSH_KNOWN_HOSTS, zero TOFU ssh-keyscan)
11. Secrets transmitted via stdin pipe (zero secrets in SSH argv)
"""
import json
from pathlib import Path
import subprocess
import sys
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def get_triggers(yaml_data: dict) -> dict:
    if "on" in yaml_data:
        return yaml_data["on"]
    if True in yaml_data:
        return yaml_data[True]
    return {}


def evaluate_ci_prerequisite(runs_payload: dict, target_sha: str, target_ref: str) -> dict[str, str]:
    """
    Deterministic reproduction of the Main CI prerequisite verification gate.
    Mirrors the inline verification step in deploy.yml (NEXUS-000D).
    """
    if target_ref not in ("refs/heads/main", "main"):
        return {"status": "blocked", "reason": f"Deploy permitted only from main. Ref: {target_ref}"}

    runs = runs_payload.get("workflow_runs", [])
    if not runs:
        return {"status": "blocked", "reason": "Ausencia de evidencia de CI (fail-closed)"}

    matching_success = [
        r for r in runs
        if r.get("head_sha") == target_sha
        and r.get("head_branch") == "main"
        and r.get("event") == "push"
        and r.get("status") == "completed"
        and r.get("conclusion") == "success"
    ]

    if not matching_success:
        non_main = [r for r in runs if r.get("head_sha") == target_sha and r.get("head_branch") != "main"]
        non_push = [r for r in runs if r.get("head_sha") == target_sha and r.get("event") != "push"]
        if non_main:
            return {"status": "blocked", "reason": "Execucoes pertencem a branches secundarias, nao a main"}
        if non_push:
            return {"status": "blocked", "reason": "Execucoes nao foram disparadas pelo evento push em main"}
        return {"status": "blocked", "reason": f"Nenhuma execucao bem-sucedida do Main CI para o SHA {target_sha}"}

    return {"status": "allowed", "run_id": str(matching_success[0].get("id"))}


def evaluate_executive_gate(
    event_name: str,
    confirmation: str,
    nexus_ref: str,
    astra_ref: str,
    secrets_dict: dict[str, str],
) -> str:
    """Simulation of full deployment interlock gate evaluation (NEXUS-000D)."""
    if event_name != "workflow_dispatch":
        return "blocked_event"
    if confirmation != "DEPLOY-TO-PRODUCTION":
        return "blocked_confirmation"
    if not nexus_ref:
        return "blocked_nexus_ref"
    if not astra_ref:
        return "blocked_astra_ref"

    required_keys = [
        "SERVER_IP",
        "SSH_PRIVATE_KEY",
        "SSH_KNOWN_HOSTS",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "EMERGENCY_PASSWORD",
        "API_KEY",
        "ALLOWED_ORIGINS",
    ]
    for k in required_keys:
        if not secrets_dict.get(k):
            return f"blocked_missing_secret_{k}"

    return "allowed_deploy"


@pytest.fixture
def deploy_yaml() -> dict:
    with open(DEPLOY_WORKFLOW, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def ci_yaml() -> dict:
    with open(CI_WORKFLOW, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestDeploymentGovernance:
    # 1. Pipeline decoupling
    def test_workflow_run_is_completely_abolished(self, deploy_yaml):
        triggers = get_triggers(deploy_yaml)
        assert "workflow_run" not in triggers, (
            "CRITICAL: workflow_run trigger MUST NOT exist in deploy.yml. "
            "Violates 'CI VERDE != AUTORIZACAO DE PRODUCAO'."
        )

    def test_no_automatic_triggers_in_deploy(self, deploy_yaml):
        triggers = get_triggers(deploy_yaml)
        prohibited_automatic_triggers = [
            "push",
            "pull_request",
            "schedule",
            "release",
            "create",
            "status",
            "check_run",
            "check_suite",
        ]
        for trig in prohibited_automatic_triggers:
            assert trig not in triggers, f"Automatic trigger '{trig}' is prohibited in deploy.yml."

    def test_workflow_dispatch_is_the_only_trigger(self, deploy_yaml):
        triggers = get_triggers(deploy_yaml)
        assert "workflow_dispatch" in triggers, "workflow_dispatch must be available in deploy.yml."
        assert set(triggers.keys()) == {"workflow_dispatch"}, (
            f"Expected only workflow_dispatch trigger, found: {set(triggers.keys())}"
        )

    # 2. P0: Script Injection Elimination
    def test_no_direct_workflow_input_interpolation_in_run_steps(self, deploy_yaml):
        """
        Enforce that NO user input or event expression is interpolated directly
        into shell run: blocks.
        """
        deploy_job = deploy_yaml["jobs"]["deploy"]
        steps = deploy_job.get("steps", [])

        for idx, step in enumerate(steps):
            run_script = step.get("run", "")
            step_name = step.get("name", f"step-{idx}")
            assert "${{" not in run_script, (
                f"Step '{step_name}' interpolates an expression directly into run: script! "
                f"All expressions must be transported strictly via env: blocks."
            )

    def test_inline_ci_verification_script_from_deploy_workflow(self):
        """Extract and execute the inline CI verification Python code from deploy.yml."""
        content = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        assert "exec(textwrap.dedent(" in content, "Expected textwrap.dedent execution in verify_ci step"

        start_marker = "exec(textwrap.dedent(" + '"""' + "\n"
        end_marker = "\n" + "          " + '"""' + "))"
        start_idx = content.find(start_marker)
        assert start_idx != -1, f"Could not find start marker: {start_marker}"
        start_idx += len(start_marker)
        end_idx = content.find(end_marker, start_idx)
        assert end_idx != -1, f"Could not find end marker: {end_marker}"

        raw_script = content[start_idx:end_idx]

        import textwrap
        dedented = textwrap.dedent(raw_script)

        def run_inline_ci(payload_dict: dict, sha: str) -> str:
            p = subprocess.run(
                [sys.executable, "-c", dedented, json.dumps(payload_dict), sha],
                capture_output=True,
                text=True,
                check=True,
            )
            return p.stdout.strip()

        # 1. Matching success on main with push event -> SUCCESS
        matching = {
            "workflow_runs": [
                {"id": 999, "head_sha": "abc1234", "head_branch": "main", "event": "push", "status": "completed", "conclusion": "success"}
            ]
        }
        assert run_inline_ci(matching, "abc1234") == "SUCCESS:999"

        # 2. Matching SHA but on feature branch -> REJECTED_BRANCH_NOT_MAIN
        branch_mismatch = {
            "workflow_runs": [
                {"id": 998, "head_sha": "abc1234", "head_branch": "feature/branch", "event": "push", "status": "completed", "conclusion": "success"}
            ]
        }
        assert run_inline_ci(branch_mismatch, "abc1234") == "REJECTED_BRANCH_NOT_MAIN"

        # 3. Matching SHA on main but event is pull_request -> REJECTED_EVENT_NOT_PUSH
        event_mismatch = {
            "workflow_runs": [
                {"id": 997, "head_sha": "abc1234", "head_branch": "main", "event": "pull_request", "status": "completed", "conclusion": "success"}
            ]
        }
        assert run_inline_ci(event_mismatch, "abc1234") == "REJECTED_EVENT_NOT_PUSH"

        # 4. Matching SHA on main and push event but failed conclusion -> REJECTED_CONCLUSION_NOT_SUCCESS
        conclusion_fail = {
            "workflow_runs": [
                {"id": 996, "head_sha": "abc1234", "head_branch": "main", "event": "push", "status": "completed", "conclusion": "failure"}
            ]
        }
        assert run_inline_ci(conclusion_fail, "abc1234") == "REJECTED_CONCLUSION_NOT_SUCCESS"

        # 5. Empty runs -> NO_RUNS
        assert run_inline_ci({"workflow_runs": []}, "abc1234") == "NO_RUNS"

    def test_confirmation_is_closed_choice(self, deploy_yaml):
        triggers = get_triggers(deploy_yaml)
        inputs = triggers["workflow_dispatch"].get("inputs", {})
        assert "confirmation" in inputs
        conf = inputs["confirmation"]
        assert conf.get("type") == "choice", "confirmation must be a choice input"
        assert conf.get("default") == "CANCEL", "confirmation default must be CANCEL"
        assert set(conf.get("options", [])) == {"CANCEL", "DEPLOY-TO-PRODUCTION"}

    # 3. P0: Authorization Model & Mandatory Inputs
    def test_workflow_dispatch_enforces_mandatory_inputs(self, deploy_yaml):
        triggers = get_triggers(deploy_yaml)
        inputs = triggers["workflow_dispatch"].get("inputs", {})

        assert "confirmation" in inputs
        assert inputs["confirmation"].get("required") is True

        assert "nexus_directive_ref" in inputs
        assert inputs["nexus_directive_ref"].get("required") is True

        assert "astra_authorization_ref" in inputs
        assert inputs["astra_authorization_ref"].get("required") is True

        assert "environment" in inputs
        assert inputs["environment"].get("default") == "production"

    def test_minimal_permissions_granted(self, deploy_yaml):
        perms = deploy_yaml.get("permissions", {})
        assert perms.get("contents") == "read", "Expected contents: read"
        assert perms.get("actions") == "read", "Expected actions: read"
        for perm_name, perm_val in perms.items():
            assert perm_val != "write", f"Write permission granted to '{perm_name}'!"

    def test_deploy_job_has_environment_and_fail_closed_condition(self, deploy_yaml):
        jobs = deploy_yaml.get("jobs", {})
        assert "deploy" in jobs
        deploy_job = jobs["deploy"]
        assert deploy_job.get("environment") == "production"

        job_if = deploy_job.get("if", "")
        assert "workflow_dispatch" in job_if
        assert "DEPLOY-TO-PRODUCTION" in job_if

    # 4. P0: Same-SHA Main CI Prerequisite Logic
    def test_commit_without_successful_ci_fails(self):
        empty_payload = {"workflow_runs": []}
        res = evaluate_ci_prerequisite(empty_payload, "target-sha-123", "refs/heads/main")
        assert res["status"] == "blocked"
        assert "fail-closed" in res["reason"]

    def test_ci_of_different_sha_fails(self):
        payload = {
            "workflow_runs": [
                {"id": 101, "head_sha": "other-sha-999", "head_branch": "main", "event": "push", "status": "completed", "conclusion": "success"}
            ]
        }
        res = evaluate_ci_prerequisite(payload, "target-sha-123", "refs/heads/main")
        assert res["status"] == "blocked"

    def test_ci_failed_conclusion_fails(self):
        payload = {
            "workflow_runs": [
                {"id": 102, "head_sha": "target-sha-123", "head_branch": "main", "event": "push", "status": "completed", "conclusion": "failure"}
            ]
        }
        res = evaluate_ci_prerequisite(payload, "target-sha-123", "refs/heads/main")
        assert res["status"] == "blocked"

    def test_ci_in_progress_fails(self):
        payload = {
            "workflow_runs": [
                {"id": 103, "head_sha": "target-sha-123", "head_branch": "main", "event": "push", "status": "in_progress", "conclusion": None}
            ]
        }
        res = evaluate_ci_prerequisite(payload, "target-sha-123", "refs/heads/main")
        assert res["status"] == "blocked"

    def test_ci_on_feature_branch_fails(self):
        payload = {
            "workflow_runs": [
                {"id": 104, "head_sha": "target-sha-123", "head_branch": "feature/branch", "event": "push", "status": "completed", "conclusion": "success"}
            ]
        }
        res = evaluate_ci_prerequisite(payload, "target-sha-123", "refs/heads/main")
        assert res["status"] == "blocked"
        assert "secundarias" in res["reason"]

    def test_ci_on_pull_request_event_fails(self):
        payload = {
            "workflow_runs": [
                {"id": 105, "head_sha": "target-sha-123", "head_branch": "main", "event": "pull_request", "status": "completed", "conclusion": "success"}
            ]
        }
        res = evaluate_ci_prerequisite(payload, "target-sha-123", "refs/heads/main")
        assert res["status"] == "blocked"
        assert "push em main" in res["reason"]

    def test_ci_correct_same_sha_main_push_success(self):
        payload = {
            "workflow_runs": [
                {"id": 106, "head_sha": "target-sha-123", "head_branch": "main", "event": "push", "status": "completed", "conclusion": "success"}
            ]
        }
        res = evaluate_ci_prerequisite(payload, "target-sha-123", "refs/heads/main")
        assert res["status"] == "allowed"
        assert res["run_id"] == "106"

    # 5. Full executive gate & exhaustive secrets validation
    def test_all_8_required_secrets_validated_before_first_ssh(self, deploy_yaml):
        steps = deploy_yaml["jobs"]["deploy"]["steps"]
        step_names = [s.get("name", "") for s in steps]

        # Ensure validation step occurs before Setup SSH Key and Copy files
        val_idx = next(i for i, n in enumerate(step_names) if "Validate all required deployment secrets" in n)
        ssh_idx = next(i for i, n in enumerate(step_names) if "Setup SSH Key" in n)
        rsync_idx = next(i for i, n in enumerate(step_names) if "Copy files" in n)

        assert val_idx < ssh_idx, "Secrets validation must occur before SSH setup!"
        assert val_idx < rsync_idx, "Secrets validation must occur before file transfer!"

        val_step = steps[val_idx]
        env_vars = val_step.get("env", {})

        expected_secrets = [
            "SERVER_IP",
            "SSH_PRIVATE_KEY",
            "SSH_KNOWN_HOSTS",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID",
            "EMERGENCY_PASSWORD",
            "API_KEY",
            "ALLOWED_ORIGINS",
        ]
        for sec in expected_secrets:
            assert sec in env_vars, f"Required secret '{sec}' is missing from secrets pre-flight validation!"

    def test_ssh_host_authenticity_pinned_and_no_tofu(self, deploy_yaml):
        content = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        assert "ssh-keyscan" not in content, (
            "CRITICAL SECURITY DEFECT: ssh-keyscan (TOFU) must NOT be present in deploy.yml!"
        )
        assert "SSH_KNOWN_HOSTS" in content, "SSH_KNOWN_HOSTS must be used for host authenticity pinning."

    def test_secrets_absent_from_ssh_argv(self, deploy_yaml):
        content = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        # Ensure secrets are piped via stdin to cat > .env
        assert "cat > /app/Meridian/.env" in content
        assert "chmod 600 /app/Meridian/.env" in content
        # Ensure no printf '%q' of secrets inside ssh argv string
        assert "TELEGRAM_BOT_TOKEN=$(printf '%q'" not in content

    def test_fail_closed_behavior_on_missing_required_secrets(self):
        valid_secrets = {
            "SERVER_IP": "1.2.3.4",
            "SSH_PRIVATE_KEY": "pem-content",
            "SSH_KNOWN_HOSTS": "pinned-hosts",
            "TELEGRAM_BOT_TOKEN": "bot-tok",
            "TELEGRAM_CHAT_ID": "chat-id",
            "EMERGENCY_PASSWORD": "pass",
            "API_KEY": "api-key",
            "ALLOWED_ORIGINS": "https://meridian.trade",
        }
        assert evaluate_executive_gate(
            "workflow_dispatch", "DEPLOY-TO-PRODUCTION", "NEXUS-001", "ASTRA-001", valid_secrets
        ) == "allowed_deploy"

        # Missing any single secret must fail-closed
        for k in valid_secrets.keys():
            incomplete = dict(valid_secrets)
            incomplete[k] = ""
            res = evaluate_executive_gate(
                "workflow_dispatch", "DEPLOY-TO-PRODUCTION", "NEXUS-001", "ASTRA-001", incomplete
            )
            assert res == f"blocked_missing_secret_{k}", f"Failed to block when '{k}' is missing!"
