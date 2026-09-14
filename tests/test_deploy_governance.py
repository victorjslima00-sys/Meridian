"""
Automated validation of Deployment Governance (NEXUS-000C)
Enforces:
1. CI VERDE != AUTORIZACAO DE PRODUCAO (CI is necessary prerequisite, not authorizer)
2. No script injection via workflow inputs (inputs transported strictly via env:)
3. Closed-choice confirmation (default CANCEL)
4. Same-SHA CI prerequisite deterministically verified (fail-closed)
5. Separation of Executive Authorization (Astra audit ref) and Technical Directive (Nexus technical ref)
6. Victor required human reviewer gate via GitHub Environment
7. Minimal permissions (contents: read, actions: read — zero write)
8. Deploy branch restricted exclusively to main
"""
import json
from pathlib import Path
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
    Deterministic reproduction of the CI prerequisite verification gate.
    Mirrors the inline verification step in deploy.yml.
    """
    if target_ref not in ("refs/heads/main", "main"):
        return {"status": "blocked", "reason": f"Deploy permitted only from main. Ref: {target_ref}"}

    runs = runs_payload.get("workflow_runs", [])
    if not runs:
        return {"status": "blocked", "reason": "Ausencia de evidencia de CI (fail-closed)"}

    matching_success = [
        r for r in runs
        if r.get("head_sha") == target_sha
        and r.get("status") == "completed"
        and r.get("conclusion") == "success"
    ]

    if not matching_success:
        return {"status": "blocked", "reason": f"Nenhuma execucao bem-sucedida do CI para o SHA {target_sha}"}

    return {"status": "allowed", "run_id": str(matching_success[0].get("id"))}


def evaluate_executive_gate(
    event_name: str,
    confirmation: str,
    nexus_ref: str,
    astra_ref: str,
    server_ip: str,
    ssh_key: str,
) -> str:
    """Simulation of full deployment interlock gate evaluation."""
    if event_name != "workflow_dispatch":
        return "blocked_event"
    if confirmation != "DEPLOY-TO-PRODUCTION":
        return "blocked_confirmation"
    if not nexus_ref:
        return "blocked_nexus_ref"
    if not astra_ref:
        return "blocked_astra_ref"
    if not server_ip or not ssh_key:
        return "blocked_secrets"
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

    # 2. P0: Anti-Script Injection
    def test_no_direct_workflow_input_interpolation_in_run_steps(self, deploy_yaml):
        """Verify no user-controllable input or expression is interpolated directly into run: blocks."""
        jobs = deploy_yaml.get("jobs", {})
        for job_name, job in jobs.items():
            for step in job.get("steps", []):
                run_content = step.get("run", "")
                if not run_content:
                    continue
                assert "${{" not in run_content, (
                    f"Step '{step.get('name')}' in job '{job_name}' interpolates '${{{{ ... }}}}' into shell run!"
                )

    def test_inline_ci_verification_script_from_deploy_workflow(self, deploy_yaml):
        """Extract and execute the exact inline Python script embedded in deploy.yml verify_ci step."""
        import subprocess
        import sys

        steps = deploy_yaml["jobs"]["deploy"]["steps"]
        verify_step = [s for s in steps if s.get("id") == "verify_ci"][0]
        run_script = verify_step["run"]

        # Extract the python3 -c script block
        assert "CI_CHECK=$(python3 -c '" in run_script
        code_part = run_script.split("CI_CHECK=$(python3 -c '", 1)[1]
        python_code = code_part.split("' \"$RUNS_JSON\"", 1)[0]

        # Case 1: Matching success
        payload_ok = json.dumps({"workflow_runs": [
            {"head_sha": "target-sha-123", "status": "completed", "conclusion": "success", "id": 777}
        ]})
        proc = subprocess.run(
            [sys.executable, "-c", python_code, payload_ok, "target-sha-123"],
            capture_output=True, text=True, check=True
        )
        assert proc.stdout.strip() == "SUCCESS:777"

        # Case 2: Different SHA
        proc = subprocess.run(
            [sys.executable, "-c", python_code, payload_ok, "other-sha-999"],
            capture_output=True, text=True, check=True
        )
        assert proc.stdout.strip() == "NO_SUCCESS"

        # Case 3: Empty runs (fail-closed)
        payload_empty = json.dumps({"workflow_runs": []})
        proc = subprocess.run(
            [sys.executable, "-c", python_code, payload_empty, "target-sha-123"],
            capture_output=True, text=True, check=True
        )
        assert proc.stdout.strip() == "NO_RUNS"

        # Case 4: Failed conclusion
        payload_fail = json.dumps({"workflow_runs": [
            {"head_sha": "target-sha-123", "status": "completed", "conclusion": "failure", "id": 888}
        ]})
        proc = subprocess.run(
            [sys.executable, "-c", python_code, payload_fail, "target-sha-123"],
            capture_output=True, text=True, check=True
        )
        assert proc.stdout.strip() == "NO_SUCCESS"

        # Case 5: In progress
        payload_running = json.dumps({"workflow_runs": [
            {"head_sha": "target-sha-123", "status": "in_progress", "conclusion": None, "id": 999}
        ]})
        proc = subprocess.run(
            [sys.executable, "-c", python_code, payload_running, "target-sha-123"],
            capture_output=True, text=True, check=True
        )
        assert proc.stdout.strip() == "NO_SUCCESS"

        # Case 6: Malformed JSON
        proc = subprocess.run(
            [sys.executable, "-c", python_code, "malformed-json", "target-sha-123"],
            capture_output=True, text=True, check=True
        )
        assert proc.stdout.strip().startswith("ERROR:")

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
        # No write permissions permitted
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

    # 4. P0: Same-SHA CI Prerequisite Logic
    def test_commit_without_successful_ci_fails(self):
        empty_payload = {"workflow_runs": []}
        res = evaluate_ci_prerequisite(empty_payload, "target-sha-123", "refs/heads/main")
        assert res["status"] == "blocked"
        assert "fail-closed" in res["reason"]

    def test_ci_of_different_sha_fails(self):
        payload = {
            "workflow_runs": [
                {"id": 101, "head_sha": "other-sha-999", "status": "completed", "conclusion": "success"}
            ]
        }
        res = evaluate_ci_prerequisite(payload, "target-sha-123", "refs/heads/main")
        assert res["status"] == "blocked"
        assert "Nenhuma execucao bem-sucedida" in res["reason"]

    def test_ci_failed_conclusion_fails(self):
        payload = {
            "workflow_runs": [
                {"id": 102, "head_sha": "target-sha-123", "status": "completed", "conclusion": "failure"}
            ]
        }
        res = evaluate_ci_prerequisite(payload, "target-sha-123", "refs/heads/main")
        assert res["status"] == "blocked"

    def test_ci_in_progress_fails(self):
        payload = {
            "workflow_runs": [
                {"id": 103, "head_sha": "target-sha-123", "status": "in_progress", "conclusion": None}
            ]
        }
        res = evaluate_ci_prerequisite(payload, "target-sha-123", "refs/heads/main")
        assert res["status"] == "blocked"

    def test_ci_correct_same_sha_success(self):
        payload = {
            "workflow_runs": [
                {"id": 104, "head_sha": "target-sha-123", "status": "completed", "conclusion": "success"}
            ]
        }
        res = evaluate_ci_prerequisite(payload, "target-sha-123", "refs/heads/main")
        assert res["status"] == "allowed"
        assert res["run_id"] == "104"

    def test_deploy_from_non_main_branch_fails(self):
        payload = {
            "workflow_runs": [
                {"id": 105, "head_sha": "target-sha-123", "status": "completed", "conclusion": "success"}
            ]
        }
        res = evaluate_ci_prerequisite(payload, "target-sha-123", "refs/heads/feature-branch")
        assert res["status"] == "blocked"
        assert "only from main" in res["reason"]

    def test_deploy_from_main_branch_allowed(self):
        payload = {
            "workflow_runs": [
                {"id": 106, "head_sha": "target-sha-123", "status": "completed", "conclusion": "success"}
            ]
        }
        res = evaluate_ci_prerequisite(payload, "target-sha-123", "refs/heads/main")
        assert res["status"] == "allowed"

    # 5. Full executive gate simulation
    def test_fail_closed_behavior_on_invalid_inputs(self):
        assert evaluate_executive_gate(
            "workflow_run", "DEPLOY-TO-PRODUCTION", "NEXUS-001", "ASTRA-001", "1.2.3.4", "key"
        ) == "blocked_event"

        assert evaluate_executive_gate(
            "workflow_dispatch", "CANCEL", "NEXUS-001", "ASTRA-001", "1.2.3.4", "key"
        ) == "blocked_confirmation"

        assert evaluate_executive_gate(
            "workflow_dispatch", "DEPLOY-TO-PRODUCTION", "", "ASTRA-001", "1.2.3.4", "key"
        ) == "blocked_nexus_ref"

        assert evaluate_executive_gate(
            "workflow_dispatch", "DEPLOY-TO-PRODUCTION", "NEXUS-001", "", "1.2.3.4", "key"
        ) == "blocked_astra_ref"

        assert evaluate_executive_gate(
            "workflow_dispatch", "DEPLOY-TO-PRODUCTION", "NEXUS-001", "ASTRA-001", "", "key"
        ) == "blocked_secrets"

        assert evaluate_executive_gate(
            "workflow_dispatch", "DEPLOY-TO-PRODUCTION", "NEXUS-001", "ASTRA-001", "1.2.3.4", ""
        ) == "blocked_secrets"

        assert evaluate_executive_gate(
            "workflow_dispatch", "DEPLOY-TO-PRODUCTION", "NEXUS-001", "ASTRA-001", "1.2.3.4", "key"
        ) == "allowed_deploy"
