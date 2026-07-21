"""
Testes do ResilientLLMClient — cadeia de fallback multi-provedor.

Contrato vigente: cada provedor (gemini, groq, cerebras, github_models,
openai) só entra na cadeia se sua chave/token estiver configurado.
generate_text/generate_text_async tentam cada provedor configurado, na
ordem, e usam a primeira resposta bem-sucedida. Só retornam None se
TODOS os provedores configurados falharem (fail-closed — o HOLD de
negócio fica no MarketAnalyst).
"""
from unittest.mock import patch, AsyncMock

import pytest

from trading_bot.core.llm_client import ResilientLLMClient, LLMResponse


@pytest.fixture(autouse=True)
def _limpa_env_de_provedores_llm(monkeypatch):
    """Isola os testes do ambiente real — sem isso, uma chave de provedor
    presente no shell (ex.: rodando localmente com .env carregado)
    vazaria pra dentro de _client_com() via os.environ.get() e quebraria
    a suposição de "só as chaves passadas estão configuradas"."""
    for var in (
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "CEREBRAS_API_KEY",
        "GITHUB_MODELS_TOKEN",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


def _resposta_ok(content: str = "resposta ok") -> LLMResponse:
    return LLMResponse(
        content=content,
        latency_ms=12.3,
        prompt_tokens=10,
        completion_tokens=5,
    )


def _client_com(**chaves) -> ResilientLLMClient:
    """Client com só as chaves passadas configuradas (as demais vazias,
    então seus provedores nunca entram na cadeia)."""
    return ResilientLLMClient(
        primary_key=chaves.get("gemini", ""),
        groq_key=chaves.get("groq", ""),
        cerebras_key=chaves.get("cerebras", ""),
        github_models_token=chaves.get("github_models", ""),
        openai_key=chaves.get("openai", ""),
    )


@patch.object(ResilientLLMClient, "_call_gemini", new_callable=AsyncMock)
def test_llm_uses_primary_when_available(mock_gemini):
    mock_gemini.return_value = _resposta_ok()

    client = _client_com(gemini="key_gemini")
    result = client.generate_text("teste")

    assert result is not None
    assert result.content == "resposta ok"
    mock_gemini.assert_awaited_once()


@patch.object(ResilientLLMClient, "_call_gemini", new_callable=AsyncMock)
def test_llm_returns_none_when_only_provider_fails(mock_gemini):
    mock_gemini.side_effect = Exception("timeout")

    client = _client_com(gemini="key_gemini")
    assert client.generate_text("teste") is None


@patch.object(ResilientLLMClient, "_call_gemini", new_callable=AsyncMock)
async def test_llm_async_returns_none_on_failure(mock_gemini):
    mock_gemini.side_effect = Exception("erro")

    client = _client_com(gemini="k1")
    assert await client.generate_text_async("teste") is None


@patch.object(ResilientLLMClient, "_call_gemini", new_callable=AsyncMock)
async def test_llm_sync_dentro_de_contexto_async_retorna_none(mock_gemini):
    """generate_text() síncrono em event loop ativo → RuntimeError → None."""
    mock_gemini.return_value = _resposta_ok()

    client = _client_com(gemini="k1")
    # Estamos dentro de um teste async (loop rodando): asyncio.run deve falhar
    assert client.generate_text("teste") is None


@patch.object(ResilientLLMClient, "_call_gemini", new_callable=AsyncMock)
async def test_llm_async_uses_primary(mock_gemini):
    mock_gemini.return_value = _resposta_ok("async ok")

    client = _client_com(gemini="k1")
    result = await client.generate_text_async("teste")

    assert result is not None
    assert result.content == "async ok"


# --- Cadeia de fallback multi-provedor -------------------------------------

@patch.object(ResilientLLMClient, "_call_groq", new_callable=AsyncMock)
@patch.object(ResilientLLMClient, "_call_gemini", new_callable=AsyncMock)
async def test_llm_falls_back_para_groq_quando_gemini_falha(mock_gemini, mock_groq):
    mock_gemini.side_effect = Exception("429 quota")
    mock_groq.return_value = _resposta_ok("groq salvou")

    client = _client_com(gemini="k_gemini", groq="k_groq")
    result = await client.generate_text_async("teste")

    assert result is not None
    assert result.content == "groq salvou"
    mock_gemini.assert_awaited_once()
    mock_groq.assert_awaited_once()


@patch.object(ResilientLLMClient, "_call_cerebras", new_callable=AsyncMock)
@patch.object(ResilientLLMClient, "_call_groq", new_callable=AsyncMock)
@patch.object(ResilientLLMClient, "_call_gemini", new_callable=AsyncMock)
async def test_llm_percorre_a_cadeia_inteira_ate_achar_um_que_funciona(
    mock_gemini, mock_groq, mock_cerebras
):
    mock_gemini.side_effect = Exception("indisponível")
    mock_groq.side_effect = Exception("rate limit")
    mock_cerebras.return_value = _resposta_ok("cerebras salvou")

    client = _client_com(gemini="k1", groq="k2", cerebras="k3")
    result = await client.generate_text_async("teste")

    assert result is not None
    assert result.content == "cerebras salvou"
    mock_gemini.assert_awaited_once()
    mock_groq.assert_awaited_once()
    mock_cerebras.assert_awaited_once()


@patch.object(ResilientLLMClient, "_call_cerebras", new_callable=AsyncMock)
@patch.object(ResilientLLMClient, "_call_groq", new_callable=AsyncMock)
@patch.object(ResilientLLMClient, "_call_gemini", new_callable=AsyncMock)
async def test_llm_retorna_none_quando_todos_os_provedores_configurados_falham(
    mock_gemini, mock_groq, mock_cerebras
):
    mock_gemini.side_effect = Exception("erro 1")
    mock_groq.side_effect = Exception("erro 2")
    mock_cerebras.side_effect = Exception("erro 3")

    client = _client_com(gemini="k1", groq="k2", cerebras="k3")
    assert await client.generate_text_async("teste") is None


@patch.object(ResilientLLMClient, "_call_cerebras", new_callable=AsyncMock)
@patch.object(ResilientLLMClient, "_call_groq", new_callable=AsyncMock)
async def test_llm_pula_provedor_sem_chave_configurada(mock_groq, mock_cerebras):
    """Sem GROQ_API_KEY, _call_groq nunca é sequer chamado — a cadeia pula
    direto pro próximo provedor configurado."""
    mock_cerebras.return_value = _resposta_ok("cerebras direto")

    client = _client_com(cerebras="k3")  # gemini e groq de propósito vazios
    result = await client.generate_text_async("teste")

    assert result is not None
    assert result.content == "cerebras direto"
    mock_groq.assert_not_awaited()


async def test_llm_sem_nenhum_provedor_configurado_retorna_none():
    client = _client_com()  # todas as chaves vazias
    assert await client.generate_text_async("teste") is None
