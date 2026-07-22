"""
Track B, Commit 1: has_cedro_key no frontend (Settings) estava hardcoded
em `false` no App.jsx, nunca lido de lugar nenhum -- o indicador "Status
da API Key no .env" mentia sempre "Faltando", exista a chave ou não.
Honest-dashboard exige ou remover, ou ler o estado real. Esta rota lê
SÓ a presença de CEDRO_API_KEY no ambiente -- nunca o valor -- e devolve
um booleano.
"""
import os

import pytest


def _get_broker_status_route():
    from backend.app import main

    return main.get_broker_status_route()


class TestBrokerStatusRoute:
    def test_true_quando_cedro_api_key_esta_configurada(self, monkeypatch):
        monkeypatch.setenv("CEDRO_API_KEY", "qualquer_valor")

        resp = _get_broker_status_route()

        assert resp == {"has_cedro_key": True}

    def test_false_quando_cedro_api_key_nao_esta_configurada(self, monkeypatch):
        monkeypatch.delenv("CEDRO_API_KEY", raising=False)

        resp = _get_broker_status_route()

        assert resp == {"has_cedro_key": False}

    def test_false_quando_cedro_api_key_esta_vazia(self, monkeypatch):
        monkeypatch.setenv("CEDRO_API_KEY", "")

        resp = _get_broker_status_route()

        assert resp == {"has_cedro_key": False}

    def test_nunca_expoe_o_valor_da_chave(self, monkeypatch):
        monkeypatch.setenv("CEDRO_API_KEY", "segredo_nao_pode_vazar")

        resp = _get_broker_status_route()

        assert "segredo_nao_pode_vazar" not in str(resp)
        assert set(resp.keys()) == {"has_cedro_key"}
