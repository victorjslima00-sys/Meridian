"""
Supervisão do worker autônomo (ai_committee_worker).

Cobre:
- heartbeat fica stale quando o loop para;
- exceção numa iteração NÃO mata o worker (próxima iteração continua);
- restart com backoff exponencial é acionado quando o worker morre de vez;
- crash-loop (falha logo após cada ciclo) chega a "stopped", não reinicia
  para sempre — graças ao reset por estabilidade;
- alerta Telegram disparado na falha de iteração, em cada restart e na
  desistência final;
- /api/status reflete o worker real (nunca "online" com worker morto).
"""
import asyncio
import datetime

import pytest
from unittest.mock import MagicMock, patch

from backend.app import worker_state as ws
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


# --- Heartbeat --------------------------------------------------------------

def test_heartbeat_fresco_apos_scan():
    state.on_worker_start()
    state.mark_scan()
    # A partir da Etapa 3 (heartbeat granular), worker_alive também exige
    # os sinais do exit_loop frescos — sem isso o sistema não é "vivo" de
    # verdade (ver TestExitLoopHeartbeat abaixo para o motivo).
    state.mark_exit_activity(effective=True)
    assert state.is_alive() is True
    assert state.snapshot()["worker_alive"] is True
    assert state.snapshot()["status"] == "online"


def test_heartbeat_stale_apos_timeout():
    state.on_worker_start()
    state.mark_scan()
    # Força o último heartbeat para além do timeout
    state.last_scan_at = ws.now_b3() - datetime.timedelta(
        seconds=ws.HEARTBEAT_TIMEOUT_SECONDS + 1
    )
    assert state.is_alive() is False
    snap = state.snapshot()
    assert snap["worker_alive"] is False
    assert snap["status"] != "online"


def test_heartbeat_falso_quando_stopped():
    """A partir da Etapa 4, 'stopped' no /api/status passou a significar
    especificamente 'exit_supervision esgotou os restarts' (o estado mais
    severo, capital exposto). Entrada sozinha marcada stopped, com saída
    saudável, agora é 'degraded' — o estado seguro (saída ainda protege).
    Ver TestFourStates.test_saida_esgotada_e_stopped_mesmo_que_pareca_saudavel
    para o 'stopped' de verdade."""
    state.on_worker_start()
    state.mark_scan()
    state.mark_exit_activity(effective=True)
    state.mark_stopped()
    assert state.is_alive() is False
    assert state.snapshot()["status"] == "degraded"


def test_worker_alive_falso_sem_nenhum_scan():
    state.on_worker_start()
    assert state.last_scan_at is None
    assert state.is_alive() is False


# --- Iteração resiliente ----------------------------------------------------

async def test_excecao_numa_iteracao_nao_mata_o_worker():
    """A 1ª iteração falha; a 2ª deve rodar normalmente."""
    from backend.app import main

    chamadas = {"n": 0}

    async def fake_cycle():
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise ValueError("schema inesperado do yfinance")
        if chamadas["n"] >= 2:
            # 2ª iteração rodou → encerra o loop de forma limpa
            raise asyncio.CancelledError()

    with patch.object(main, "_run_one_scan_cycle", side_effect=fake_cycle), \
         patch.object(ws, "SCAN_INTERVAL_SECONDS", 0), \
         patch.object(main, "_alerta_telegram") as mock_alerta:
        with pytest.raises(asyncio.CancelledError):
            await main.ai_committee_worker()

    assert chamadas["n"] >= 2  # a falha da 1ª não impediu a 2ª
    assert mock_alerta.called   # alerta na falha de iteração


async def test_iteracao_bem_sucedida_atualiza_heartbeat():
    from backend.app import main

    chamadas = {"n": 0}

    async def fake_cycle():
        chamadas["n"] += 1
        if chamadas["n"] >= 2:
            raise asyncio.CancelledError()

    assert state.last_scan_at is None
    with patch.object(main, "_run_one_scan_cycle", side_effect=fake_cycle), \
         patch.object(ws, "SCAN_INTERVAL_SECONDS", 0):
        with pytest.raises(asyncio.CancelledError):
            await main.ai_committee_worker()

    assert state.last_scan_at is not None  # mark_scan foi chamado


# --- Supervisor: restart com backoff ---------------------------------------

async def test_restart_com_backoff_e_desistencia():
    from backend.app import main

    delays = []

    async def fake_sleep(d):
        delays.append(d)

    async def sempre_falha():
        raise RuntimeError("worker morreu de vez")

    with patch.object(main, "ai_committee_worker", side_effect=sempre_falha), \
         patch.object(main.asyncio, "sleep", side_effect=fake_sleep), \
         patch.object(main, "_alerta_telegram") as mock_alerta:
        await main.worker_supervisor()

    # MAX_RESTARTS backoffs antes de desistir (na tentativa MAX+1 marca stopped)
    assert delays == [1, 2, 4, 8, 16]
    assert state.status == "stopped"
    # Alerta em cada restart (5) + desistência final (1)
    assert mock_alerta.call_count == ws.MAX_RESTARTS + 1


async def test_backoff_respeita_cap(monkeypatch):
    from backend.app import main

    monkeypatch.setattr(ws, "MAX_RESTARTS", 8)
    delays = []

    async def fake_sleep(d):
        delays.append(d)

    async def sempre_falha():
        raise RuntimeError("boom")

    with patch.object(main, "ai_committee_worker", side_effect=sempre_falha), \
         patch.object(main.asyncio, "sleep", side_effect=fake_sleep), \
         patch.object(main, "_alerta_telegram"):
        await main.worker_supervisor()

    assert delays == [1, 2, 4, 8, 16, 30, 30, 30]  # capado em BACKOFF_CAP=30
    assert state.status == "stopped"


# --- Crash-loop NÃO reinicia para sempre -----------------------------------

async def test_crash_loop_chega_a_stopped(monkeypatch):
    """
    Worker completa exatamente 1 ciclo (mark_scan) e então falha, repetidamente.
    Com reset por estabilidade, restart_count nunca zera → chega a stopped.
    """
    from backend.app import main

    monkeypatch.setattr(ws, "STABLE_RESET_SECONDS", 10**9)  # nunca por tempo

    async def um_ciclo_depois_falha():
        state.mark_scan()  # 1 ciclo "bem-sucedido"
        raise RuntimeError("morre logo após o ciclo")

    async def fake_sleep(d):
        pass

    with patch.object(main, "ai_committee_worker", side_effect=um_ciclo_depois_falha), \
         patch.object(main.asyncio, "sleep", side_effect=fake_sleep), \
         patch.object(main, "_alerta_telegram") as mock_alerta:
        await main.worker_supervisor()

    assert state.status == "stopped"
    assert state.restart_count > ws.MAX_RESTARTS
    # Alerta de desistência definitiva foi disparado
    assert any("PARADO" in str(c.args) for c in mock_alerta.call_args_list)


async def test_worker_estavel_zera_restart_count(monkeypatch):
    """Worker que roda >= STABLE_RESET_CYCLES entre falhas se mantém vivo."""
    from backend.app import main

    monkeypatch.setattr(ws, "STABLE_RESET_SECONDS", 10**9)
    state.restart_count = 3
    state.on_worker_start()
    for _ in range(ws.STABLE_RESET_CYCLES):
        state.mark_scan()
    assert state.restart_count == 0


# --- /api/status ------------------------------------------------------------

def test_api_status_reflete_worker_morto():
    from backend.app import main

    # Chamada direta à rota (sem TestClient, para não disparar o lifespan e
    # subir o worker real). Estado forçado stale.
    state.on_worker_start()
    state.mark_scan()
    state.last_scan_at = ws.now_b3() - datetime.timedelta(
        seconds=ws.HEARTBEAT_TIMEOUT_SECONDS + 1
    )

    resp = main.get_status()
    assert resp["worker_alive"] is False
    assert resp["status"] != "online"


def test_api_status_online_quando_worker_vivo():
    from backend.app import main

    state.on_worker_start()
    state.mark_scan()
    state.mark_exit_activity(effective=True)  # ver nota na Etapa 3 acima
    resp = main.get_status()
    assert resp["worker_alive"] is True
    assert resp["status"] == "online"


# --- /api/status expõe o portão de entradas (honest-dashboard, Bloco 1) -----
#
# O front precisa mostrar POR QUE as entradas estão bloqueadas sem calcular
# nada sozinho — os motivos (circuit_breaker/exit_loop_unhealthy/
# exit_loop_exhausted) e os contadores de restart/sticky do exit_loop
# precisam vir prontos do backend. snapshot() já calculava
# exit_restart_count/exit_gate_sticky_block internamente, mas get_status()
# não os repassava; motivos_bloqueio é campo novo, persistido por
# _avaliar_portao_de_entradas a cada avaliação (não existia antes — os
# motivos eram calculados e descartados no mesmo ciclo).

class TestApiStatusExpoePortaoDeEntradas:
    def test_expoe_exit_restart_count_e_sticky_block(self):
        from backend.app import main

        state.exit_supervision.restart_count = 2
        state.set_exit_gate_sticky_block()

        resp = main.get_status()

        assert resp["exit_restart_count"] == 2
        assert resp["exit_gate_sticky_block"] is True

    async def test_motivos_bloqueio_vazio_quando_liberado(self):
        from backend.app import main

        state.mark_exit_activity(effective=True)
        with patch(
            "trading_bot.risk.circuit_breaker.CircuitBreaker.from_config",
            return_value=_fake_breaker(True),
        ):
            await main._avaliar_portao_de_entradas()

        resp = main.get_status()
        assert resp["motivos_bloqueio"] == []

    async def test_motivos_bloqueio_reflete_ultima_avaliacao_real(self):
        from backend.app import main

        state.mark_exit_activity(effective=True)
        state.set_exit_gate_sticky_block()
        with patch(
            "trading_bot.risk.circuit_breaker.CircuitBreaker.from_config",
            return_value=_fake_breaker(False),
        ):
            await main._avaliar_portao_de_entradas()

        resp = main.get_status()
        assert "exit_loop_exhausted" in resp["motivos_bloqueio"]
        assert "circuit_breaker" in resp["motivos_bloqueio"]


# --- dashboard-depth Bloco D: nada fabricado sobrevive --------------------
#
# /api/ecosystem e /api/market_tape pareciam órfãs (o frontend não as usava
# mais depois do honest-dashboard Bloco 4), mas na verdade continuavam
# sendo chamadas e renderizadas (fita de cotações fake no topbar) -- e
# active_agents: 3 em /api/status nunca foi limpo. Estes testes travam a
# ausência dos três daqui pra frente.
class TestNadaFabricadoSobrevive:
    def test_status_nao_expoe_active_agents_fabricado(self):
        from backend.app import main

        resp = main.get_status()
        assert "active_agents" not in resp

    def test_rotas_fake_ecosystem_e_market_tape_nao_existem(self):
        from backend.app import main

        paths = {getattr(r, "path", None) for r in main.app.routes}
        assert "/api/ecosystem" not in paths
        assert "/api/market_tape" not in paths


# --- Heartbeat granular do exit_loop (P3-A Etapa 3) -------------------------
#
# Dois sinais, propositalmente separados: last_exit_activity_at prova que o
# LAÇO está rodando; last_effective_exit_scan_at prova que ele está de fato
# PROTEGENDO (toda posição ativa avaliada com preço confiável, ou nenhuma
# existia). worker_alive exige os dois frescos -- um laço vivo mas inefetivo
# ("girando" sem avaliar nada por rate limit/feed fora do ar) não pode
# passar por saudável, é o padrão do poller que ficou 40 min girando em
# erro de SSL: processo vivo, trabalho zero.

class TestExitLoopHeartbeat:
    def test_zero_posicoes_ativas_mantem_worker_alive(self):
        """Zero posições ativas é uma passada trivialmente efetiva --
        nada podia ter ficado desprotegido -- e não pode derrubar o
        sinal de saúde."""
        state.on_worker_start()
        state.mark_scan()
        state.mark_exit_activity(effective=True)
        assert state.is_alive() is True

    def test_falha_transitoria_no_exit_loop_nao_derruba_worker_alive(self):
        """1 passada ruim isolada, seguida de 1 boa: não pode virar
        alarme -- senão qualquer soluço passageiro de rate limit vira
        ruído, e ruído demais treina todo mundo a ignorar o alarme."""
        state.on_worker_start()
        state.mark_scan()
        state.mark_exit_activity(effective=True)
        state.mark_exit_activity(effective=False)
        assert state.is_alive() is True  # ainda bem dentro do timeout
        state.mark_exit_activity(effective=True)  # próxima passada recupera
        assert state.is_alive() is True

    def test_degradacao_sustentada_do_exit_loop_derruba_worker_alive(self):
        """Sem NENHUMA passada efetiva por mais que HEARTBEAT_TIMEOUT_SECONDS
        -- o caso real (Yahoo fora do ar por minutos) -- worker_alive cai."""
        state.on_worker_start()
        state.mark_scan()
        state.mark_exit_activity(effective=True)
        # Última vez que uma passada foi efetiva: há mais que o timeout.
        state.last_effective_exit_scan_at = ws.now_b3() - datetime.timedelta(
            seconds=ws.HEARTBEAT_TIMEOUT_SECONDS + 1
        )
        assert state.is_alive() is False

    def test_exit_loop_vivo_mas_inutil_nao_conta_como_vivo(self):
        """O caso central desta etapa: last_exit_activity_at FRESCO (o
        laço está rodando de verdade, a cada iteração) mas
        last_effective_exit_scan_at VELHO (nenhuma avaliação confiável há
        minutos) -- worker_alive precisa cair. 'Estou rodando' não é a
        mesma coisa que 'estou protegendo'."""
        state.on_worker_start()
        state.mark_scan()
        state.mark_exit_activity(effective=True)
        state.last_effective_exit_scan_at = ws.now_b3() - datetime.timedelta(
            seconds=ws.HEARTBEAT_TIMEOUT_SECONDS + 1
        )
        state.last_exit_activity_at = ws.now_b3()  # o laço acabou de rodar
        assert state.is_alive() is False
        assert (ws.now_b3() - state.last_exit_activity_at).total_seconds() < 1

    def test_worker_alive_falso_sem_nenhuma_atividade_do_exit_loop(self):
        """Simétrico ao test_worker_alive_falso_sem_nenhum_scan já
        existente: antes da primeira iteração do exit_loop completar,
        os campos são None -- não fresco, não vivo. Mesmo padrão já
        usado para last_scan_at, agora também para os sinais de saída."""
        state.on_worker_start()
        state.mark_scan()
        assert state.last_exit_activity_at is None
        assert state.last_effective_exit_scan_at is None
        assert state.is_alive() is False

    def test_api_status_expoe_timestamps_do_exit_loop_separadamente(self):
        from backend.app import main

        state.on_worker_start()
        state.mark_scan()
        state.mark_exit_activity(effective=True)
        resp = main.get_status()
        assert resp["last_exit_activity_at"] is not None
        assert resp["last_effective_exit_scan_at"] is not None

    async def test_exit_loop_efetivo_atualiza_os_dois_sinais(self):
        """Fiação de ponta a ponta: exit_loop() de verdade chama
        mark_exit_activity com o retorno de _run_exit_scan()."""
        from backend.app import main

        chamadas = {"n": 0}

        async def fake_scan():
            chamadas["n"] += 1
            if chamadas["n"] >= 2:
                raise asyncio.CancelledError()
            return True  # passada efetiva

        assert state.last_exit_activity_at is None
        assert state.last_effective_exit_scan_at is None
        with patch.object(main, "_run_exit_scan", side_effect=fake_scan), \
             patch.object(ws, "EXIT_INTERVAL_SECONDS", 0):
            with pytest.raises(asyncio.CancelledError):
                await main.exit_loop()

        assert state.last_exit_activity_at is not None
        assert state.last_effective_exit_scan_at is not None

    async def test_exit_loop_inefetivo_marca_atividade_sem_marcar_efetividade(self):
        """Passada que roda mas retorna False (preço não confiável em
        algum ticker ativo): last_exit_activity_at avança,
        last_effective_exit_scan_at NÃO — é essa diferença que faz o
        laço vivo-mas-inútil aparecer no sinal."""
        from backend.app import main

        chamadas = {"n": 0}

        async def fake_scan():
            chamadas["n"] += 1
            if chamadas["n"] >= 2:
                raise asyncio.CancelledError()
            return False  # passada NÃO efetiva

        with patch.object(main, "_run_exit_scan", side_effect=fake_scan), \
             patch.object(ws, "EXIT_INTERVAL_SECONDS", 0):
            with pytest.raises(asyncio.CancelledError):
                await main.exit_loop()

        assert state.last_exit_activity_at is not None
        assert state.last_effective_exit_scan_at is None


# --- Etapa 4: supervisor de dois laços --------------------------------------
#
# Contabilidade de restart é SEMPRE por laço (nunca global): a instabilidade
# de um não pode derrubar a supervisão do outro, que pode estar são. O
# reset por estabilidade da saída usa SÓ STABLE_RESET_SECONDS (Opção A
# confirmada) — a 5s/ciclo, "5 ciclos" (métrica da entrada, calibrada pra
# 60s/ciclo) representa só 25s, tempo curto demais pra provar qualquer
# coisa. O bloqueio sticky de entradas (exit_gate_sticky_block) só é limpo
# por reinício do processo — NUNCA auto-recuperação quando a saída volta a
# ficar saudável: esgotar MAX_RESTARTS significa algo estruturalmente
# quebrado, e isso exige olhar antes de voltar a operar.

class TestLoopSupervisionStateIsolation:
    def test_exit_supervision_e_independente_da_entrada(self):
        """Crashes na saída não tocam em nada da entrada, e vice-versa —
        são objetos de contabilidade totalmente separados."""
        state.on_worker_start()
        for _ in range(10):
            state.exit_supervision.record_crash()
        assert state.restart_count == 0
        assert state.status != "stopped"

        state.exit_supervision = ws.LoopSupervisionState(use_cycles_for_stability=False)
        for _ in range(10):
            state.record_crash()
        assert state.exit_supervision.restart_count == 0

    def test_exit_supervision_esgotando_nao_marca_entrada_como_stopped(self):
        state.on_worker_start()
        state.exit_supervision.on_start()
        for _ in range(ws.MAX_RESTARTS + 1):
            state.exit_supervision.record_crash()
        state.exit_supervision.mark_stopped()
        assert state.exit_supervision.status == "stopped"
        assert state.status == "running"  # entrada intocada


class TestExitStabilityResetOptionA:
    """Opção A confirmada: reset do restart_count da saída usa só tempo
    (STABLE_RESET_SECONDS), nunca contagem de ciclos."""

    def test_muitos_ciclos_rapidos_nao_resetam_sem_tempo_suficiente(self):
        sup = ws.LoopSupervisionState(use_cycles_for_stability=False)
        sup.on_start()
        sup.record_crash()
        assert sup.restart_count == 1
        # 1000 "ciclos" (bem mais que STABLE_RESET_CYCLES=5), mas o
        # relógio não andou — não pode resetar baseado em contagem.
        for _ in range(1000):
            sup.mark_cycle_complete()
        assert sup.restart_count == 1

    def test_reseta_apos_stable_reset_seconds_mesmo_com_zero_ciclos_extra(self):
        sup = ws.LoopSupervisionState(use_cycles_for_stability=False)
        sup.on_start()
        sup.record_crash()
        sup.restart_epoch_start = ws.now_b3() - datetime.timedelta(
            seconds=ws.STABLE_RESET_SECONDS + 1
        )
        sup.mark_cycle_complete()  # só precisa de UMA reavaliação
        assert sup.restart_count == 0

    def test_entrada_continua_usando_ciclos_normalmente(self):
        """Regressão: a mudança pra saída não pode afetar o comportamento
        já existente da entrada (que usa ciclos OU tempo)."""
        state.restart_count = 1
        state.on_worker_start()
        for _ in range(ws.STABLE_RESET_CYCLES):
            state.mark_scan()
        assert state.restart_count == 0


class TestExitGateSticky:
    def test_sticky_bloqueia_mesmo_com_circuit_breaker_liberado(self):
        state.set_exit_gate_sticky_block()
        assert state.exit_gate_sticky_block is True

    def test_sticky_sobrevive_saida_voltando_a_ficar_saudavel(self):
        """O ponto central: esgotar restarts é uma decisão estrutural, não
        um estado de saúde momentâneo. Saída voltando a responder não
        limpa o sticky sozinha."""
        state.set_exit_gate_sticky_block()
        state.mark_exit_activity(effective=True)  # saída "recupera"
        assert state.is_exit_loop_healthy() is True  # saúde dinâmica ok
        assert state.exit_gate_sticky_block is True  # mas sticky persiste

    def test_apenas_reset_limpa_o_sticky(self):
        state.set_exit_gate_sticky_block()
        state.reset()  # equivalente a reinício do processo
        assert state.exit_gate_sticky_block is False


class TestFourStates:
    """Os 4 estados de /api/status, na ordem de prioridade: stopped >
    unprotected > degraded > online."""

    def test_tudo_saudavel_e_online(self):
        state.on_worker_start()
        state.mark_scan()
        state.mark_exit_activity(effective=True)
        assert state._compute_status() == "online"

    def test_entrada_morta_saida_saudavel_e_degraded(self):
        state.on_worker_start()
        state.mark_scan()
        state.mark_exit_activity(effective=True)
        state.last_scan_at = ws.now_b3() - datetime.timedelta(
            seconds=ws.HEARTBEAT_TIMEOUT_SECONDS + 1
        )
        assert state._compute_status() == "degraded"

    def test_saida_viva_mas_inefetiva_e_unprotected_nunca_online(self):
        state.on_worker_start()
        state.mark_scan()
        state.mark_exit_activity(effective=True)
        state.last_effective_exit_scan_at = ws.now_b3() - datetime.timedelta(
            seconds=ws.HEARTBEAT_TIMEOUT_SECONDS + 1
        )
        state.last_exit_activity_at = ws.now_b3()  # laço rodando de verdade
        assert state._compute_status() == "unprotected"
        assert state._compute_status() != "online"

    def test_unprotected_tem_prioridade_sobre_degraded(self):
        """Entrada TAMBÉM morta ao mesmo tempo que saída inefetiva —
        continua unprotected, não degraded (saída manda na severidade)."""
        state.on_worker_start()
        state.mark_scan()
        state.mark_exit_activity(effective=True)
        state.last_scan_at = ws.now_b3() - datetime.timedelta(
            seconds=ws.HEARTBEAT_TIMEOUT_SECONDS + 1
        )
        state.last_effective_exit_scan_at = ws.now_b3() - datetime.timedelta(
            seconds=ws.HEARTBEAT_TIMEOUT_SECONDS + 1
        )
        assert state._compute_status() == "unprotected"

    def test_saida_esgotada_e_stopped_mesmo_que_pareca_saudavel(self):
        """stopped tem prioridade máxima — mesmo que os timestamps
        pareçam frescos (ex.: exit_loop foi morto e reiniciado manualmente
        de outro jeito), o sticky de esgotamento é decisivo."""
        state.on_worker_start()
        state.mark_scan()
        state.mark_exit_activity(effective=True)
        state.exit_supervision.mark_stopped()
        assert state._compute_status() == "stopped"

    def test_snapshot_worker_alive_so_true_quando_online(self):
        state.on_worker_start()
        state.mark_scan()
        state.mark_exit_activity(effective=True)
        assert state.snapshot()["worker_alive"] is True
        assert state.snapshot()["status"] == "online"

        state.exit_supervision.mark_stopped()
        assert state.snapshot()["worker_alive"] is False
        assert state.snapshot()["status"] == "stopped"


# --- Etapa 4: exit_loop_supervisor -------------------------------------

class TestExitLoopSupervisor:
    async def test_restart_com_backoff_e_desistencia_isolado_da_entrada(self):
        """Mesmo formato de test_restart_com_backoff_e_desistencia, mas
        pro laço de saída — e prova que a entrada não é afetada."""
        from backend.app import main

        delays = []

        async def fake_sleep(d):
            delays.append(d)

        async def sempre_falha():
            raise RuntimeError("exit_loop morreu de vez")

        with patch.object(main, "exit_loop", side_effect=sempre_falha), \
             patch.object(main.asyncio, "sleep", side_effect=fake_sleep), \
             patch.object(main, "_alerta_telegram") as mock_alerta, \
             patch.object(main, "_formatar_posicoes_abertas_para_alerta", return_value="(nenhuma)"):
            await main.exit_loop_supervisor()

        assert delays == [1, 2, 4, 8, 16]
        assert state.exit_supervision.status == "stopped"
        assert mock_alerta.call_count == ws.MAX_RESTARTS + 1

        # Isolamento: a entrada não foi tocada por nada disso.
        assert state.status == "starting"
        assert state.restart_count == 0

    async def test_backoff_respeita_cap_no_exit_loop(self, monkeypatch):
        from backend.app import main

        monkeypatch.setattr(ws, "MAX_RESTARTS", 8)
        delays = []

        async def fake_sleep(d):
            delays.append(d)

        async def sempre_falha():
            raise RuntimeError("boom")

        with patch.object(main, "exit_loop", side_effect=sempre_falha), \
             patch.object(main.asyncio, "sleep", side_effect=fake_sleep), \
             patch.object(main, "_alerta_telegram"), \
             patch.object(main, "_formatar_posicoes_abertas_para_alerta", return_value="(nenhuma)"):
            await main.exit_loop_supervisor()

        assert delays == [1, 2, 4, 8, 16, 30, 30, 30]
        assert state.exit_supervision.status == "stopped"

    async def test_esgotamento_seta_o_sticky_de_bloqueio(self):
        from backend.app import main

        async def sempre_falha():
            raise RuntimeError("boom")

        async def fake_sleep(d):
            pass

        assert state.exit_gate_sticky_block is False
        with patch.object(main, "exit_loop", side_effect=sempre_falha), \
             patch.object(main.asyncio, "sleep", side_effect=fake_sleep), \
             patch.object(main, "_alerta_telegram"), \
             patch.object(main, "_formatar_posicoes_abertas_para_alerta", return_value="(nenhuma)"):
            await main.exit_loop_supervisor()

        assert state.exit_gate_sticky_block is True

    async def test_alerta_de_desistencia_contem_lista_de_posicoes(self):
        """Exigência obrigatória: o alerta final tem que listar as
        posições abertas (ticker, entrada, stop, alvo) — não pode ser só
        'algo grave aconteceu'."""
        from backend.app import main

        async def sempre_falha():
            raise RuntimeError("boom")

        async def fake_sleep(d):
            pass

        posicoes_fake = (
            "- PETR4.SA: entrada R$ 30.00, stop R$ 28.00, alvo R$ 40.00\n"
            "- VALE3.SA: entrada R$ 60.00, stop R$ 55.00, alvo R$ 70.00"
        )
        with patch.object(main, "exit_loop", side_effect=sempre_falha), \
             patch.object(main.asyncio, "sleep", side_effect=fake_sleep), \
             patch.object(main, "_alerta_telegram") as mock_alerta, \
             patch.object(
                 main, "_formatar_posicoes_abertas_para_alerta",
                 return_value=posicoes_fake,
             ):
            await main.exit_loop_supervisor()

        mensagens = [str(c.args[0]) for c in mock_alerta.call_args_list]
        mensagem_final = mensagens[-1]
        assert "PETR4.SA" in mensagem_final
        assert "stop R$ 28.00" in mensagem_final
        assert "VALE3.SA" in mensagem_final

    async def test_falha_da_entrada_nao_afeta_contador_da_saida(self):
        """O outro lado do isolamento: worker_supervisor falhando não
        toca em state.exit_supervision."""
        from backend.app import main

        async def sempre_falha():
            raise RuntimeError("worker morreu de vez")

        async def fake_sleep(d):
            pass

        with patch.object(main, "ai_committee_worker", side_effect=sempre_falha), \
             patch.object(main.asyncio, "sleep", side_effect=fake_sleep), \
             patch.object(main, "_alerta_telegram"):
            await main.worker_supervisor()

        assert state.status == "stopped"
        assert state.exit_supervision.restart_count == 0
        assert state.exit_supervision.status == "starting"
        assert state.exit_gate_sticky_block is False
