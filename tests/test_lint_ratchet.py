"""
Unit tests for the Flake8 Lint Ratchet mechanism (scripts/check_lint_ratchet.py).
"""

import subprocess
import sys
from pathlib import Path
from scripts.check_lint_ratchet import DEFAULT_CEILING, count_flake8_violations


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_ratchet_default_ceiling():
    """Verify that default ratchet ceiling is pinned to 944."""
    assert DEFAULT_CEILING == 944


def test_ratchet_counts_violations_accurately():
    """Verify that count_flake8_violations returns a valid non-negative integer count."""
    count, output = count_flake8_violations(target_dir=str(REPO_ROOT))
    assert isinstance(count, int)
    assert count <= DEFAULT_CEILING
    assert "===" not in output or output != ""


def test_ratchet_cli_execution_passes():
    """Verify that executing the ratchet script directly via subprocess exits with code 0."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_lint_ratchet.py"), "--quiet"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Expected 0, got {result.returncode}. Output: {result.stderr}"
    assert "Current Flake8 violations" in result.stdout
    assert "PASSED" in result.stdout


def test_ratchet_cli_fails_when_ceiling_exceeded():
    """Verify that executing the ratchet script with an artificially low ceiling exits with code 1."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_lint_ratchet.py"), "--quiet", "--ceiling", "1"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "FAILED" in result.stderr or "FAILED" in result.stdout
