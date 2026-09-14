"""Local append-only research storage. Hash integrity does not authenticate a source."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Identifier(BaseModel):
    model_config = ConfigDict(strict=True)
    value: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$')

    @field_validator('value')
    @classmethod
    def not_reserved(cls, value):
        if value.upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))}:
            raise ValueError('reserved_identifier')
        return value


class StoredManifest(BaseModel):
    model_config = ConfigDict(strict=True, extra='allow')
    layer: str
    dataset: str
    file_path: str
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class LakehouseStorageManager:
    """Exclusive writes; incomplete writes stay visible to the integrity inventory.

    Filesystem permissions remain necessary: hashes and local manifests do not
    establish financial accuracy, source provenance, or resistance to an attacker
    who can modify both. Silver storage does not imply data approval.
    """

    def __init__(self, base_dir: str = 'data/lakehouse'):
        self.base_dir = str(Path(base_dir).resolve())
        for layer in ('bronze', 'silver', 'gold'):
            path = Path(self.base_dir) / layer
            self._within(path, Path(self.base_dir))
            path.mkdir(parents=True, exist_ok=True)
            setattr(self, f'{layer}_dir', str(path))

    @staticmethod
    def _within(path: Path, root: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(root.resolve()):
            raise ValueError('path_outside_layer')
        return path

    def _folder(self, layer: str, dataset: str) -> Path:
        Identifier(value=dataset)
        root = Path(getattr(self, f'{layer}_dir'))
        self._within(root, Path(self.base_dir))
        folder = self._within(root / dataset, root)
        folder.mkdir(exist_ok=True)
        return folder

    @staticmethod
    def _compute_hash(content_bytes: bytes) -> str:
        return hashlib.sha256(content_bytes).hexdigest()

    def _save(self, layer, folder, filename, manifest_name, payload, metadata):
        root = Path(getattr(self, f'{layer}_dir'))
        target = self._within(folder / filename, root)
        manifest = self._within(folder / manifest_name, root)
        # Refuse partial/legacy pairs too. 'xb' also arbitrates competing writers.
        if target.exists() or manifest.exists():
            raise FileExistsError('record_already_exists')
        metadata.update(file_path=str(target), sha256=self._compute_hash(payload), size_bytes=len(payload))
        encoded = json.dumps(metadata, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')
        with target.open('xb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        with manifest.open('xb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        return metadata

    def save_bronze(self, dataset_name: str, record_id: str, payload: Any) -> dict[str, Any]:
        Identifier(value=record_id)
        folder = self._folder('bronze', dataset_name)
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')
        return self._save('bronze', folder, f'{record_id}.json', f'{record_id}.manifest.json', encoded, {
            'layer': 'bronze', 'dataset': dataset_name, 'record_id': record_id,
            'ingested_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })

    def save_bronze_raw(
        self,
        dataset_name: str,
        record_id: str,
        raw_bytes: bytes,
        extension: str = "json",
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        Identifier(value=record_id)
        if not isinstance(raw_bytes, (bytes, bytearray)):
            raise TypeError("raw_bytes_must_be_bytes")
        if not re.fullmatch(r"^[a-zA-Z0-9]{1,10}$", extension):
            raise ValueError("invalid_extension")
        folder = self._folder("bronze", dataset_name)
        meta = {
            "layer": "bronze",
            "dataset": dataset_name,
            "record_id": record_id,
            "extension": extension,
            "ingested_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        if metadata:
            meta.update(metadata)
        return self._save(
            "bronze",
            folder,
            f"{record_id}.{extension}",
            f"{record_id}.manifest.json",
            bytes(raw_bytes),
            meta,
        )

    def read_bronze(
        self,
        dataset_name: str,
        record_id: str,
        extension: str = "json",
    ) -> tuple[bytes, dict[str, Any]]:
        Identifier(value=record_id)
        folder = self._folder("bronze", dataset_name)
        payload_file = folder / f"{record_id}.{extension}"
        manifest_file = folder / f"{record_id}.manifest.json"
        if not payload_file.is_file() or not manifest_file.is_file():
            raise FileNotFoundError("bronze_record_not_found")
        meta = StoredManifest.model_validate_json(manifest_file.read_bytes())
        raw_bytes = payload_file.read_bytes()
        digest = self._compute_hash(raw_bytes)
        if digest != meta.sha256:
            raise ValueError("hash_mismatch")
        return raw_bytes, json.loads(manifest_file.read_text(encoding="utf-8"))

    def save_silver(self, dataset_name: str, df: pd.DataFrame) -> dict[str, Any]:
        folder = self._folder('silver', dataset_name)
        return self._save('silver', folder, 'data.csv', 'manifest.json', df.to_csv(index=False).encode('utf-8'), {
            'layer': 'silver', 'dataset': dataset_name, 'row_count': len(df), 'columns': list(df.columns),
            'promoted_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })

    def generate_integrity_manifest(self) -> dict[str, Any]:
        issues, verified = [], []
        counts = {'bronze': 0, 'silver': 0}
        def issue(path, reason):
            issues.append({'path': str(path), 'reason': reason})
        for layer in counts:
            root = Path(getattr(self, f'{layer}_dir'))
            try:
                self._within(root, Path(self.base_dir))
            except ValueError:
                issue(root, 'path_outside_layer')
                continue
            pairs = {}
            for current, dirs, files in os.walk(root, followlinks=False):
                for directory in list(dirs):
                    path = Path(current) / directory
                    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                        dirs.remove(directory)
                        issue(path, 'linked_directory')
                for name in files:
                    path = Path(current) / name
                    if layer == 'bronze':
                        if name.endswith('.manifest.json'):
                            stem = name[:-len('.manifest.json')]
                            matched = None
                            for cand_ext in ('.json', '.csv', '.bin', '.txt'):
                                cand = path.with_name(stem + cand_ext)
                                if cand.is_file():
                                    matched = cand
                                    break
                            payload = matched if matched else path.with_name(stem + '.json')
                            pairs[payload] = path
                        elif any(name.endswith(ext) for ext in ('.json', '.csv', '.bin', '.txt')):
                            counts[layer] += 1
                            stem = Path(name).stem
                            pairs[path] = path.with_name(f"{stem}.manifest.json")
                    elif name == 'manifest.json':
                        pairs[path.with_name('data.csv')] = path
                    elif name.endswith('.csv'):
                        counts[layer] += 1
                        pairs[path] = path.with_name('manifest.json')
            for payload, manifest in sorted(pairs.items()):
                try:
                    self._within(payload, root)
                    self._within(manifest, root)
                    if payload.is_symlink() or manifest.is_symlink():
                        raise ValueError('linked_file')
                except ValueError:
                    issue(payload, 'unsafe_path')
                    continue
                if not payload.is_file():
                    issue(payload, 'missing_payload')
                    continue
                if not manifest.is_file():
                    issue(manifest, 'missing_manifest')
                    continue
                try:
                    meta = StoredManifest.model_validate_json(manifest.read_bytes())
                    if meta.layer != layer or meta.dataset != payload.parent.name or Path(meta.file_path).resolve() != payload.resolve():
                        raise ValueError('manifest_identity_mismatch')
                    Identifier(value=meta.dataset)
                except (ValueError, OSError):
                    issue(manifest, 'invalid_manifest')
                    continue
                try:
                    digest = self._compute_hash(payload.read_bytes())
                except OSError:
                    issue(payload, 'unreadable_payload')
                    continue
                if digest != meta.sha256:
                    issue(payload, 'hash_mismatch')
                else:
                    verified.append({'path': str(payload), 'sha256': digest})
        return {
            'generator': 'Orion-LakehouseStorageManager',
            'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'lakehouse_root': self.base_dir, 'bronze_count': counts['bronze'], 'silver_count': counts['silver'],
            'verified_count': len(verified), 'verified_files': verified, 'issues': issues,
            'integrity_ok': not issues, 'source_authenticity_verified': False,
        }
