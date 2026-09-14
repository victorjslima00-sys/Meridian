"""
Testes unitarios para o Sincronizador Google Drive — Orion Data Engineering
"""
import os
from unittest.mock import patch, MagicMock
import pytest
from trading_bot.data.exporters.gdrive_sync import GoogleDriveSyncManager


def test_sync_local_drive(tmp_path):
    # Simula pasta espelhada local do Google Drive
    drive_mirror = tmp_path / "Meu Drive" / "Meridian_Decisoes"
    drive_mirror.mkdir(parents=True)

    source_file = tmp_path / "planilha_teste.xlsx"
    source_file.write_text("conteudo binario simulado")

    syncer = GoogleDriveSyncManager(local_drive_dir=str(drive_mirror))
    res = syncer.sync_file(str(source_file))

    assert res["status"] == "synced_local"
    assert os.path.exists(drive_mirror / "planilha_teste.xlsx")
    assert res["target_path"] == str(drive_mirror / "planilha_teste.xlsx")


def test_sync_fallback_when_no_credentials_and_no_drive(tmp_path):
    source_file = tmp_path / "planilha_teste.xlsx"
    source_file.write_text("conteudo binario simulado")

    # Sem pasta local e sem API key
    syncer = GoogleDriveSyncManager(local_drive_dir=None, credentials_path=None)
    res = syncer.sync_file(str(source_file))

    # Deve realizar fallback seguro salvando em staging local sem crashar o bot
    assert res["status"] == "staged_locally"
    assert "fallback_path" in res
