import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_live_demo_blocks_before_unverified_collection():
    source = ROOT / 'scripts/live_demonstration.py'
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'run_live_demonstration')
    calls = []
    def forbidden(*a, **kw):
        calls.append(True)
        raise AssertionError('unverified_collection')
    namespace = {'BacenSgsMiner': forbidden}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
    with pytest.raises(RuntimeError, match='unverified_live_demonstration'):
        namespace['run_live_demonstration']()
    assert not calls
