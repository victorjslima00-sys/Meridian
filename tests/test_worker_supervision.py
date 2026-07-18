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
from unittest.mock import patch

from backend.app import worker_state as ws
from backend.app.worker_state import state


@pytest.fixture(autouse=True)
def _reset_state():
    state.reset()
    yield
    state.reset()


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
    state.on_worker_start()
    state.mark_scan()
    state.mark_stopped()
    assert state.is_alive() is False
    assert state.snapshot()["status"] == "stopped"


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
