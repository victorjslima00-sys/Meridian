"""
P3-A Etapa 4 — portão ÚNICO de entradas.
============================================
Antes desta etapa, só o circuit breaker decidia se novas entradas podiam
abrir. Agora a saúde do exit_loop também é motivo de bloqueio — e os dois
precisam responder pela MESMA via, nunca por caminhos de decisão
separados que podem um dia divergir ("um diz liberado, outro diz
bloqueado" num sistema que move dinheiro é inaceitável).

Motivos acumuláveis: circuit_breaker, exit_loop_unhealthy (dinâmico — se
resolve sozinho quando a saída volta a ficar saudável), exit_loop_exhausted
(sticky — só reinício do processo limpa, ver worker_state.py).
"""
import time
from unittest.mock import MagicMock, patch

import pytest

from backend.app.worker_state import state


@pytest.fixture(autouse=True)
def _reset_state():
    state.reset()
    yield
    state.reset()


def _fake_breaker(pode_operar: bool):
    breaker = MagicMock()
    breaker.can_trade.return_value = pode_operar
    return breaker


class TestPortaoUnicoDeEntradas:
    async def test_tudo_saudavel_libera_entradas(self):
        from backend.app import main

        state.mark_exit_activity(effective=True)
        with patch(
            "trading_bot.risk.circuit_breaker.CircuitBreaker.from_config",
            return_value=_fake_breaker(True),
        ):
            liberado, motivos = await main._avaliar_portao_de_entradas()

        assert liberado is True
        assert motivos == []

    async def test_circuit_breaker_sozinho_bloqueia(self):
        from backend.app import main

        state.mark_exit_activity(effective=True)
        with patch(
            "trading_bot.risk.circuit_breaker.CircuitBreaker.from_config",
            return_value=_fake_breaker(False),
        ):
            liberado, motivos = await main._avaliar_portao_de_entradas()

        assert liberado is False
        assert motivos == ["circuit_breaker"]

    async def test_saida_nao_saudavel_bloqueia_mesmo_com_circuit_breaker_liberado(
        self,
    ):
        """O cenário central: saída morre → entradas bloqueadas enquanto
        ela está caída, mesmo com circuit breaker liberado."""
        from backend.app import main

        # last_exit_activity_at/last_effective_exit_scan_at nunca setados
        # = saída nunca reportou nada = não saudável.
        with patch(
            "trading_bot.risk.circuit_breaker.CircuitBreaker.from_config",
            return_value=_fake_breaker(True),
        ):
            liberado, motivos = await main._avaliar_portao_de_entradas()

        assert liberado is False
        assert motivos == ["exit_loop_unhealthy"]

    async def test_motivos_sao_acumulaveis(self):
        """Circuit breaker E saída não saudável ao mesmo tempo -> os dois
        motivos aparecem, nenhum esconde o outro."""
        from backend.app import main

        with patch(
            "trading_bot.risk.circuit_breaker.CircuitBreaker.from_config",
            return_value=_fake_breaker(False),
        ):
            liberado, motivos = await main._avaliar_portao_de_entradas()

        assert liberado is False
        assert "circuit_breaker" in motivos
        assert "exit_loop_unhealthy" in motivos
        assert len(motivos) == 2

    async def test_saida_recupera_dinamicamente_libera_entradas_de_novo(self):
        """Bloqueio dinâmico (não sticky): saída ficando saudável de novo,
        ANTES de esgotar restarts, libera entradas de novo."""
        from backend.app import main

        with patch(
            "trading_bot.risk.circuit_breaker.CircuitBreaker.from_config",
            return_value=_fake_breaker(True),
        ):
            liberado_antes, motivos_antes = await main._avaliar_portao_de_entradas()
            assert liberado_antes is False
            assert "exit_loop_unhealthy" in motivos_antes

            state.mark_exit_activity(effective=True)  # saída recupera

            liberado_depois, motivos_depois = await main._avaliar_portao_de_entradas()
            assert liberado_depois is True
            assert motivos_depois == []

    async def test_sticky_bloqueia_mesmo_com_saida_saudavel_agora(self):
        """O ponto central do sticky: mesmo que a saída volte a responder
        (saudável dinamicamente), o esgotamento continua bloqueando."""
        from backend.app import main

        state.mark_exit_activity(effective=True)  # saída saudável agora
        state.set_exit_gate_sticky_block()  # mas já esgotou antes

        with patch(
            "trading_bot.risk.circuit_breaker.CircuitBreaker.from_config",
            return_value=_fake_breaker(True),
        ):
            liberado, motivos = await main._avaliar_portao_de_entradas()

        assert liberado is False
        assert motivos == ["exit_loop_exhausted"]

    async def test_sticky_e_circuit_breaker_juntos_sao_acumulaveis(self):
        from backend.app import main

        state.mark_exit_activity(effective=True)
        state.set_exit_gate_sticky_block()

        with patch(
            "trading_bot.risk.circuit_breaker.CircuitBreaker.from_config",
            return_value=_fake_breaker(False),
        ):
            liberado, motivos = await main._avaliar_portao_de_entradas()

        assert liberado is False
        assert "circuit_breaker" in motivos
        assert "exit_loop_exhausted" in motivos

    async def test_circuit_breaker_indisponivel_conta_como_bloqueio(self):
        """Fail-closed já existente: erro ao consultar o circuit breaker
        bloqueia, não libera por omissão."""
        from backend.app import main

        state.mark_exit_activity(effective=True)
        with patch(
            "trading_bot.risk.circuit_breaker.CircuitBreaker.from_config",
            side_effect=RuntimeError("indisponível"),
        ):
            liberado, motivos = await main._avaliar_portao_de_entradas()

        assert liberado is False
        assert "circuit_breaker" in motivos


class _FakeAppConfig:
    def __init__(self, tickers):
        self._tickers = tickers

    def get(self, *keys, default=None):
        if keys == ("_universe", "tickers"):
            return self._tickers
        return default


class TestLembretePeriodicoDeEsgotamento:
    """P3-A Etapa 4 (exigência promovida a obrigatória): enquanto o
    sticky de exit_loop_exhausted persistir, um lembrete periódico é
    reenviado — mesmo padrão 'não silencia, não spama' do dedup de preço
    (Etapa 2d), cooldown próprio (EXIT_LOOP_EXHAUSTED_REMINDER_SECONDS).
    Testado fim a fim via _run_one_scan_cycle, não só o mecanismo de
    dedup isolado (já coberto na Etapa 2d)."""

    async def _rodar_ciclo(self, main):
        fake_cfg = _FakeAppConfig([])  # universo vazio: ciclo termina rápido
        fake_breaker = MagicMock()
        fake_breaker.can_trade.return_value = True
        with patch(
            "trading_bot.core.config.AppConfig.load", return_value=fake_cfg
        ), patch(
            "trading_bot.risk.circuit_breaker.CircuitBreaker.from_config",
            return_value=fake_breaker,
        ), patch.object(main, "has_snapshot_for", return_value=True):
            await main._run_one_scan_cycle()

    async def test_primeiro_ciclo_com_sticky_dispara_lembrete_com_posicoes(self):
        from backend.app import main

        state.set_exit_gate_sticky_block()
        with patch.object(main, "_alerta_telegram") as mock_alerta, \
             patch.object(
                 main, "_formatar_posicoes_abertas_para_alerta",
                 return_value="- PETR4.SA: entrada R$ 30.00, stop R$ 28.00, alvo R$ 40.00",
             ):
            await self._rodar_ciclo(main)

        assert mock_alerta.called
        mensagens = [str(c.args[0]) for c in mock_alerta.call_args_list]
        assert any("PETR4.SA" in m for m in mensagens)

    async def test_segundo_ciclo_imediato_nao_repete_lembrete(self):
        from backend.app import main

        state.set_exit_gate_sticky_block()
        with patch.object(main, "_alerta_telegram") as mock_alerta, \
             patch.object(
                 main, "_formatar_posicoes_abertas_para_alerta", return_value="(nenhuma)"
             ):
            await self._rodar_ciclo(main)
            count_apos_primeiro = mock_alerta.call_count
            await self._rodar_ciclo(main)
            count_apos_segundo = mock_alerta.call_count

        assert count_apos_segundo == count_apos_primeiro  # sem repetição

    async def test_apos_cooldown_lembrete_dispara_de_novo(self):
        from backend.app import main

        state.set_exit_gate_sticky_block()
        with patch.object(main, "EXIT_LOOP_EXHAUSTED_REMINDER_SECONDS", 0.05), \
             patch.object(main, "_alerta_telegram") as mock_alerta, \
             patch.object(
                 main, "_formatar_posicoes_abertas_para_alerta", return_value="(nenhuma)"
             ):
            await self._rodar_ciclo(main)
            count_apos_primeiro = mock_alerta.call_count
            time.sleep(0.12)
            await self._rodar_ciclo(main)
            count_apos_segundo = mock_alerta.call_count

        assert count_apos_segundo > count_apos_primeiro
