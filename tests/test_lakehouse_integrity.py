import json
from pathlib import Path

import pandas as pd
import pytest

from trading_bot.data.lakehouse.storage_manager import LakehouseStorageManager


@pytest.mark.parametrize('bad', ['../escape', '..', '/absolute', 'a/b', r'a\b', 'CON', 'a:stream', 'a.'])
def test_identifiers_reject_escape(tmp_path, bad):
    manager = LakehouseStorageManager(str(tmp_path / 'lake'))
    with pytest.raises(ValueError):
        manager.save_bronze(bad, 'record', {})
    with pytest.raises(ValueError):
        manager.save_bronze('dataset', bad, {})
    with pytest.raises(ValueError):
        manager.save_silver(bad, pd.DataFrame({'x': [1]}))


@pytest.mark.parametrize('layer', ['bronze', 'silver'])
def test_existing_payload_and_manifest_never_overwritten(tmp_path, layer):
    manager = LakehouseStorageManager(str(tmp_path / 'lake'))
    def save(value):
        return manager.save_bronze('dataset', 'record', value) if layer == 'bronze' else manager.save_silver('dataset', pd.DataFrame({'x': [value]}))
    first = save(1)
    snapshot = {p: p.read_bytes() for p in Path(manager.base_dir).rglob('*') if p.is_file()}
    with pytest.raises(FileExistsError):
        save(2)
    assert {p: p.read_bytes() for p in snapshot} == snapshot


@pytest.mark.parametrize('mutation,reason', [('payload', 'hash_mismatch'), ('missing_payload', 'missing_payload'), ('missing_manifest', 'missing_manifest'), ('manifest', 'invalid_manifest')])
def test_inventory_detects_invalid_evidence(tmp_path, mutation, reason):
    manager = LakehouseStorageManager(str(tmp_path / 'lake'))
    metadata = manager.save_bronze('dataset', 'record', {'x': 1})
    payload = Path(metadata['file_path'])
    manifest = payload.with_name('record.manifest.json')
    if mutation == 'payload':
        payload.write_text('{}', encoding='utf-8')
    elif mutation == 'missing_payload':
        payload.unlink()
    elif mutation == 'missing_manifest':
        manifest.unlink()
    else:
        manifest.write_text('{}', encoding='utf-8')
    inventory = manager.generate_integrity_manifest()
    assert inventory['integrity_ok'] is False
    assert reason in [issue['reason'] for issue in inventory['issues']]
    assert inventory['source_authenticity_verified'] is False


def test_good_inventory_checks_hash_without_claiming_source_authenticity(tmp_path):
    manager = LakehouseStorageManager(str(tmp_path / 'lake'))
    manager.save_bronze('dataset', 'record', {'x': 1})
    manager.save_silver('dataset', pd.DataFrame({'x': [1]}))
    inventory = manager.generate_integrity_manifest()
    assert inventory['verified_count'] == 2
    assert inventory['integrity_ok'] is True
    assert inventory['source_authenticity_verified'] is False
