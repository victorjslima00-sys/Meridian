"""
honest-dashboard Bloco 2: /api/positions devolve PnL em R$, capital
alocado e preço atual JA CALCULADOS pelo backend. Antes, o frontend
recalculava tudo isso sozinho a partir de entry_price/shares/pnl_pct —
contra a regra do CLAUDE.md ("no frontend, tudo que parece dado É dado
vindo da API, ou não existe"). O banco/schema real é usado (não mock),
mesmo padrão de tests/test_exit_loop.py.

dashboard-depth (2026-07-20): "Patrimônio Total" estava igual a
"Caixa Disponível" e não reagia a ganho/perda das posições abertas —
bug real de cálculo, não só de exibição, achado pelo usuário. Causa
raiz: get_portfolio() sobrescrevia a coluna real `patrimonio_total`
(o "cofre" fora do alcance do bot, movimentado por
depositar_no_disponivel/retirar_do_disponivel) com o valor de
`saldo_disponivel`. O "Patrimônio Total" exibido precisa ser
patrimonio_total (cofre) + compute_current_equity() (caixa livre +
mark-to-market das posições ativas) — só assim ele sobe quando um
trade ganha e desce quando perde.
"""
import datetime
import os
import sqlite3
import tempfile
from unittest.mock import patch

import pytest

from backend.app.data import database as database_module


@pytest.fixture
def temp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    original_path = database_module.DB_PATH
    database_module.DB_PATH = path
    try:
        database_module.init_db()
    finally:
        database_module.DB_PATH = original_path
    yield path
    os.unlink(path)


def _insert_trade(path, **overrides):
    defaults = dict(
        ticker="PETR4.SA", side="BUY", shares=10.0, entry_price=30.0,
        exit_price=None, target_price=40.0, stop_loss=28.0,
        entry_date=datetime.datetime.now(), exit_date=None,
        pnl_pct=0.0, exit_reason=None, ai_rationale="teste", status="active",
    )
    defaults.update(overrides)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO trades (ticker, side, shares, entry_price, exit_price, "
        "target_price, stop_loss, entry_date, exit_date, pnl_pct, exit_reason, "
        "ai_rationale, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            defaults["ticker"], defaults["side"], defaults["shares"],
            defaults["entry_price"], defaults["exit_price"], defaults["target_price"],
            defaults["stop_loss"], defaults["entry_date"], defaults["exit_date"],
            defaults["pnl_pct"], defaults["exit_reason"], defaults["ai_rationale"],
            defaults["status"],
        ),
    )
    conn.commit()
    conn.close()


def _get_positions(temp_db_path):
    from backend.app import main

    original_path = database_module.DB_PATH
    database_module.DB_PATH = temp_db_path
    try:
        return main.get_positions_route()
    finally:
        database_module.DB_PATH = original_path


def _set_portfolio(path, patrimonio_total, saldo_disponivel, em_posicoes):
    """init_db() já insere uma linha default (0.0, 100.0, 0.0) — este
    helper sobrescreve pra cenários de teste com valores distintos entre
    os três campos, essencial pra provar que get_portfolio() não os
    confunde entre si."""
    conn = sqlite3.connect(path)
    conn.execute(
        "UPDATE portfolio SET patrimonio_total=?, saldo_disponivel=?, em_posicoes=? "
        "WHERE id = (SELECT id FROM portfolio ORDER BY id DESC LIMIT 1)",
        (patrimonio_total, saldo_disponivel, em_posicoes),
    )
    conn.commit()
    conn.close()


class TestPosicaoAtivaTrazCalculosProntos:
    def test_alocado_current_price_e_pnl_monetario_para_buy(self, temp_db_path):
        _insert_trade(
            temp_db_path, ticker="PETR4.SA", side="BUY", shares=10.0,
            entry_price=30.0, pnl_pct=10.0, status="active",
        )

        resp = _get_positions(temp_db_path)

        pos = resp["active_positions"][0]
        assert pos["alocado"] == pytest.approx(300.0)
        assert pos["current_price"] == pytest.approx(33.0)
        assert pos["pnl_monetario"] == pytest.approx(30.0)

    def test_current_price_deriva_na_direcao_certa_para_sell(self, temp_db_path):
        _insert_trade(
            temp_db_path, ticker="VALE3.SA", side="SELL", shares=5.0,
            entry_price=60.0, pnl_pct=5.0, status="active",
        )

        resp = _get_positions(temp_db_path)

        pos = resp["active_positions"][0]
        # SELL com PnL positivo = preço caiu em relação à entrada.
        assert pos["current_price"] == pytest.approx(57.0)
        assert pos["pnl_monetario"] == pytest.approx(15.0)


class TestPosicaoFechadaTrazExitReasonECalculos:
    def test_exit_reason_alocado_pnl_monetario_e_current_price_igual_exit_price(
        self, temp_db_path
    ):
        _insert_trade(
            temp_db_path, ticker="ITUB4.SA", side="BUY", shares=20.0,
            entry_price=25.0, exit_price=27.5, pnl_pct=10.0,
            exit_reason="Take Profit hit at 27.5", status="closed",
            exit_date=datetime.datetime.now(),
        )

        resp = _get_positions(temp_db_path)

        pos = resp["closed_positions"][0]
        assert pos["exit_reason"] == "Take Profit hit at 27.5"
        assert pos["alocado"] == pytest.approx(500.0)
        assert pos["pnl_monetario"] == pytest.approx(50.0)
        assert pos["current_price"] == pytest.approx(27.5)


class TestGetPortfolioPreservaPatrimonioReal:
    """patrimonio_total é a coluna real do "cofre" (fora do alcance do
    bot, movimentada só por depositar_no_disponivel/retirar_do_disponivel)
    — não pode ser confundida com saldo_disponivel (capital entregue ao
    bot). Bug real encontrado pelo usuário: os dois apareciam sempre
    iguais no dashboard porque get_portfolio() sobrescrevia um pelo
    outro."""

    def test_patrimonio_total_nao_e_sobrescrito_por_saldo_disponivel(self, temp_db_path):
        _set_portfolio(
            temp_db_path, patrimonio_total=50.0, saldo_disponivel=80.0, em_posicoes=20.0
        )
        original_path = database_module.DB_PATH
        database_module.DB_PATH = temp_db_path
        try:
            pf = database_module.get_portfolio()
        finally:
            database_module.DB_PATH = original_path

        assert pf["patrimonio_total"] == pytest.approx(50.0)
        assert pf["saldo_disponivel"] == pytest.approx(80.0)
        assert pf["saldo_livre"] == pytest.approx(60.0)


class TestCapitalNaRotaDePosicoesReflexteGanhoEPerda:
    """"Patrimônio Total" exibido no dashboard = patrimonio_total (cofre,
    fora do bot) + compute_current_equity() (caixa livre do bot +
    mark-to-market das posições ativas) — só essa soma sobe quando uma
    posição ganha e desce quando perde, o comportamento que o usuário
    esperava e não via."""

    def test_patrimonio_total_soma_cofre_com_equity_ao_vivo_do_bot(self, temp_db_path):
        _set_portfolio(
            temp_db_path, patrimonio_total=30.0, saldo_disponivel=100.0, em_posicoes=40.0
        )
        _insert_trade(
            temp_db_path, ticker="PETR4.SA", side="BUY", shares=10.0,
            entry_price=30.0, pnl_pct=0.0, status="active",
        )

        with patch("backend.app.data.feed.get_current_price", return_value=33.0):
            resp = _get_positions(temp_db_path)

        # caixa_livre = saldo_disponivel(100) - em_posicoes(40) = 60
        # mtm = 10 ações * 33.0 = 330
        # equity_sob_gestao = 60 + 330 = 390
        # patrimonio_total exibido = cofre(30) + equity_sob_gestao(390) = 420
        assert resp["capital"]["patrimonio_total"] == pytest.approx(420.0)
        assert resp["capital"]["patrimonio_reservado"] == pytest.approx(30.0)

    def test_patrimonio_total_sobe_com_ganho_e_desce_com_perda(self, temp_db_path):
        _set_portfolio(
            temp_db_path, patrimonio_total=0.0, saldo_disponivel=100.0, em_posicoes=30.0
        )
        _insert_trade(
            temp_db_path, ticker="VALE3.SA", side="BUY", shares=5.0,
            entry_price=60.0, pnl_pct=0.0, status="active",
        )

        with patch("backend.app.data.feed.get_current_price", return_value=66.0):
            resp_ganho = _get_positions(temp_db_path)
        with patch("backend.app.data.feed.get_current_price", return_value=60.0):
            resp_neutro = _get_positions(temp_db_path)
        with patch("backend.app.data.feed.get_current_price", return_value=54.0):
            resp_perda = _get_positions(temp_db_path)

        # Preço subiu (66 > entrada 60) -> patrimônio maior que no preço de entrada.
        # Preço caiu (54 < entrada 60) -> patrimônio menor que no preço de entrada.
        assert resp_ganho["capital"]["patrimonio_total"] > resp_neutro["capital"]["patrimonio_total"]
        assert resp_perda["capital"]["patrimonio_total"] < resp_neutro["capital"]["patrimonio_total"]
