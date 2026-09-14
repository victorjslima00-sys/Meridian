"""Exercise only the entry function; never import the unreviewed pipeline."""
import ast
from pathlib import Path
import pytest


def test_pipeline_blocks_before_collection_or_publication():
    source = Path(__file__).resolve().parents[1] / 'scripts/run_executive_data_pipeline.py'
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run_pipeline')
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('unreviewed_side_effect')
    namespace = {name: forbidden for name in ('BacenSgsMiner', 'CvmEventsMiner',
        'MarketKalmanFilter', 'ExecutiveWorkbookExporter', 'GoogleDriveSyncManager')}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
    with pytest.raises(RuntimeError, match='unverified_executive_pipeline'):
        namespace['run_pipeline']()
    assert calls == []
