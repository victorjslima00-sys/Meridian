"""Bridge forwarder for Nexus Pre-Tool Guard.
Ensures hook execution resolves identically when invoked from workspace root or .agents directory.
"""
from pathlib import Path
import runpy

_TARGET = Path(__file__).resolve().parent.parent / ".agents" / "scripts" / "pre_tool_guard.py"
runpy.run_path(str(_TARGET), run_name="__main__")
