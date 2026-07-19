import os
from unittest.mock import patch

import pytest

from backend.app.runtime_config import RuntimeConfig
from backend.app.security import get_api_key, validate_security_config


def test_runtime_config_reads_execution_and_risk_values(tmp_path):
    settings = tmp_path / "settings.yaml"
    universe = tmp_path / "universe.yaml"
    settings.write_text(
        "execution:\n  mode: manual\nrisk:\n  kelly_fraction: 0.25\n  max_positions: 3\n  max_position_fraction: 0.10\nllm:\n  failure_policy: hold\n",
        encoding="utf-8",
    )
    universe.write_text("universe:\n  tickers: [PETR4]\n", encoding="utf-8")

    cfg = RuntimeConfig.load(str(settings), str(universe))

    assert cfg.execution_mode == "manual"
    assert cfg.kelly_fraction == 0.25
    assert cfg.max_positions == 3
    assert cfg.llm_failure_policy == "hold"
    assert cfg.autonomous_entries_enabled is False


def test_invalid_execution_mode_fails_closed(tmp_path):
    settings = tmp_path / "settings.yaml"
    universe = tmp_path / "universe.yaml"
    settings.write_text("execution:\n  mode: real_money\n", encoding="utf-8")
    universe.write_text("universe:\n  tickers: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="execution.mode"):
        RuntimeConfig.load(str(settings), str(universe))


def test_api_key_has_no_insecure_default(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    assert get_api_key() is None
    with pytest.raises(RuntimeError, match="API_KEY"):
        validate_security_config()


def test_api_key_is_loaded_only_from_environment(monkeypatch):
    monkeypatch.setenv("API_KEY", "a-long-random-test-key")
    assert get_api_key() == "a-long-random-test-key"
    validate_security_config()


class TestVerifyApiKeyEnforcement:
    """verify_api_key() é a função que de fato barra/libera requisições
    (não só os helpers de configuração de startup acima). Testada via um
    app FastAPI minimal e isolado — sem tocar o lifespan pesado de
    backend/app/main.py (que dispara workers/loops em background)."""

    def _client(self):
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        from backend.app.security import verify_api_key

        app = FastAPI()

        @app.get("/protected")
        def protected(api_key: str = Depends(verify_api_key)):
            return {"ok": True}

        return TestClient(app)

    def test_header_ausente_e_rejeitado(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "a-valid-strong-key-123456")
        r = self._client().get("/protected")
        # 401, não 403: header ausente nunca chega a verify_api_key — é
        # barrado antes, pelo auto_error=True do próprio APIKeyHeader.
        assert r.status_code == 401

    def test_chave_errada_e_rejeitada(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "a-valid-strong-key-123456")
        r = self._client().get("/protected", headers={"X-API-Key": "chave-errada"})
        assert r.status_code == 403

    def test_chave_correta_e_aceita(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "a-valid-strong-key-123456")
        r = self._client().get(
            "/protected", headers={"X-API-Key": "a-valid-strong-key-123456"}
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True}


class TestEmergencyStopAutenticacaoEFailClosed:
    """/api/system/emergency_stop é a rota mais destrutiva do arquivo
    (fecha TODAS as posições ativas) — precisa exigir X-API-Key como as
    outras rotas de escrita, falhar FECHADO (não 200) quando
    EMERGENCY_PASSWORD não está configurada, e não estourar em senha
    ausente no corpo da requisição.

    system_emergency_stop é montada num app FastAPI isolado (não o app
    real de backend/app/main.py) — mesmo raciocínio de
    TestVerifyApiKeyEnforcement: evita disparar o lifespan pesado."""

    def _client(self, monkeypatch, emergency_password="senha-forte-teste"):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from backend.app import main

        api_key = "chave-forte-teste-123456"
        monkeypatch.setenv("API_KEY", api_key)
        monkeypatch.setattr(main, "EMERGENCY_PASSWORD", emergency_password)

        app = FastAPI()
        app.post("/api/system/emergency_stop")(main.system_emergency_stop)
        return TestClient(app), api_key

    def test_sem_x_api_key_e_rejeitado(self, monkeypatch):
        client, _ = self._client(monkeypatch)
        r = client.post(
            "/api/system/emergency_stop",
            json={"action": "stop", "password": "senha-forte-teste"},
        )
        assert r.status_code in (401, 403)

    def test_com_api_key_mas_senha_de_emergencia_errada_e_rejeitada(
        self, monkeypatch
    ):
        client, api_key = self._client(monkeypatch)
        r = client.post(
            "/api/system/emergency_stop",
            json={"action": "stop", "password": "senha-errada"},
            headers={"X-API-Key": api_key},
        )
        assert r.status_code == 401

    def test_senha_ausente_no_corpo_nao_derruba_com_500(self, monkeypatch):
        client, api_key = self._client(monkeypatch)
        r = client.post(
            "/api/system/emergency_stop",
            json={"action": "stop"},  # sem "password"
            headers={"X-API-Key": api_key},
        )
        assert r.status_code == 401  # não 500

    def test_emergency_password_nao_configurada_falha_fechado(self, monkeypatch):
        client, api_key = self._client(monkeypatch, emergency_password="")
        r = client.post(
            "/api/system/emergency_stop",
            json={"action": "stop", "password": "qualquer"},
            headers={"X-API-Key": api_key},
        )
        assert r.status_code == 503  # não 200

    def test_com_api_key_e_senha_corretas_executa(self, monkeypatch):
        client, api_key = self._client(monkeypatch)
        with patch("backend.app.data.database.get_active_trades", return_value=[]):
            r = client.post(
                "/api/system/emergency_stop",
                json={"action": "stop", "password": "senha-forte-teste"},
                headers={"X-API-Key": api_key},
            )
        assert r.status_code == 200
        assert r.json()["status"] == "success"
