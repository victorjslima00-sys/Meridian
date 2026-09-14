"""The CLI must not turn example/unverified signals into portfolio writes."""
import argparse
import ast
import logging
from pathlib import Path
import sys
from typing import List, Optional

import pytest


@pytest.mark.parametrize("argv", [[], ["--session-id", "resume", "--db-path", "existing.db", "--storage-dir", "reports"]])
def test_cli_blocks_before_runner_or_database_access(argv, capsys):
    source = Path(__file__).resolve().parents[1] / "scripts/run_paper_session.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("paper_runner_must_not_start")

    namespace = {
        "argparse": argparse, "logging": logging, "sys": sys,
        "Optional": Optional, "List": List,
        "PaperSessionRunner": forbidden,
        "logger": logging.getLogger(__name__),
    }
    exec(compile(ast.Module(body=[main], type_ignores=[]), str(source), "exec"), namespace)
    assert namespace["main"](argv) == 2
    assert "unverified_paper_session_inputs" in capsys.readouterr().err
    assert calls == []
