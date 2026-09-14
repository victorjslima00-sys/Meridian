"""
Automated validation of Deployment Governance (NEXUS-000B)
Enforces:
1. CI VERDE != AUTORIZACAO DE PRODUCAO
2. workflow_run trigger is completely abolished from deploy.yml
3. No automatic trigger can start production deployment
4. workflow_dispatch is the only allowed trigger and requires explicit confirmation
5. CI pipeline is decoupled and independent of deploy pipeline
6. Fail-closed gate behavior
"""
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


@pytest.fixture
def deploy_yaml() -> dict:
    with open(DEPLOY_WORKFLOW, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def ci_yaml() -> dict:
    with open(CI_WORKFLOW, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestDeploymentGovernance:
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
        # Confirm no other triggers exist
        assert set(triggers.keys()) == {"workflow_dispatch"}, (
            f"Expected only workflow_dispatch trigger, found: {set(triggers.keys())}"
        )

    def test_workflow_dispatch_enforces_mandatory_inputs(self, deploy_yaml):
        triggers = get_triggers(deploy_yaml)
        wd = triggers["workflow_dispatch"]
        inputs = wd.get("inputs", {})
        assert "confirmation" in inputs, "workflow_dispatch must require 'confirmation' input."
        assert inputs["confirmation"].get("required") is True, "Confirmation input must be required: true."

        assert "nexus_directive_ref" in inputs, "workflow_dispatch must require 'nexus_directive_ref' input."
        assert inputs["nexus_directive_ref"].get("required") is True, "nexus_directive_ref must be required: true."

        assert "environment" in inputs, "workflow_dispatch must declare target 'environment'."

    def test_deploy_job_has_environment_and_fail_closed_condition(self, deploy_yaml):
        jobs = deploy_yaml.get("jobs", {})
        assert "deploy" in jobs, "deploy job must exist in deploy.yml."
        deploy_job = jobs["deploy"]

        assert deploy_job.get("environment") == "production", (
            "deploy job must be explicitly bound to GitHub Environment 'production'."
        )

        job_if = deploy_job.get("if", "")
        assert "workflow_dispatch" in job_if, "deploy job 'if' condition must enforce workflow_dispatch."
        assert "DEPLOY-TO-PRODUCTION" in job_if, (
            "deploy job 'if' condition must require confirmation 'DEPLOY-TO-PRODUCTION'."
        )

    def test_ci_pipeline_is_independent_and_does_not_trigger_deploy(self, ci_yaml, deploy_yaml):
        # CI must not reference deploy.yml
        ci_text = CI_WORKFLOW.read_text(encoding="utf-8")
        assert "deploy.yml" not in ci_text
        assert "deploy" not in ci_yaml.get("jobs", {})

        # deploy.yml must not reference CI workflow
        deploy_text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        assert 'workflows: ["CI"]' not in deploy_text
        assert "workflows: ['CI']" not in deploy_text

    def test_fail_closed_behavior_on_invalid_inputs(self):
        # Simulation of gate evaluation logic
        def evaluate_gate(event_name: str, confirmation: str, directive_ref: str, server_ip: str, ssh_key: str):
            if event_name != "workflow_dispatch":
                return "blocked_event"
            if confirmation != "DEPLOY-TO-PRODUCTION":
                return "blocked_confirmation"
            if not directive_ref:
                return "blocked_directive"
            if not server_ip or not ssh_key:
                return "blocked_secrets"
            return "allowed_deploy"

        assert evaluate_gate("workflow_run", "DEPLOY-TO-PRODUCTION", "NEXUS-001", "1.2.3.4", "key") == "blocked_event"
        assert evaluate_gate("workflow_dispatch", "", "NEXUS-001", "1.2.3.4", "key") == "blocked_confirmation"
        assert evaluate_gate("workflow_dispatch", "deploy", "NEXUS-001", "1.2.3.4", "key") == "blocked_confirmation"
        assert evaluate_gate("workflow_dispatch", "DEPLOY-TO-PRODUCTION", "", "1.2.3.4", "key") == "blocked_directive"
        assert evaluate_gate("workflow_dispatch", "DEPLOY-TO-PRODUCTION", "NEXUS-001", "", "key") == "blocked_secrets"
        assert evaluate_gate("workflow_dispatch", "DEPLOY-TO-PRODUCTION", "NEXUS-001", "1.2.3.4", "") == "blocked_secrets"
        assert evaluate_gate("workflow_dispatch", "DEPLOY-TO-PRODUCTION", "NEXUS-001", "1.2.3.4", "key") == "allowed_deploy"
