"""
Testes do ResilientLLMClient (API atual, pós llm-bridge).

O contrato vigente: _call_gemini é o único provedor; em qualquer falha,
generate_text/generate_text_async retornam None (o fallback de negócio
fica no MarketAnalyst, que aciona lógica matemática + alerta Telegram).
"""
from unittest.mock import patch, AsyncMock

from trading_bot.core.llm_client import ResilientLLMClient, LLMResponse


def _resposta_ok(content: str = "resposta ok") -> LLMResponse:
    return LLMResponse(
        content=content,
        latency_ms=12.3,
        prompt_tokens=10,
        completion_tokens=5,
    )


@patch.object(ResilientLLMClient, "_call_gemini", new_callable=AsyncMock)
def test_llm_uses_primary_when_available(mock_gemini):
    mock_gemini.return_value = _resposta_ok()

    client = ResilientLLMClient(primary_key="key_gemini")
    result = client.generate_text("teste")

    assert result is not None
    assert result.content == "resposta ok"
    mock_gemini.assert_awaited_once()


@patch.object(ResilientLLMClient, "_call_gemini", new_callable=AsyncMock)
def test_llm_returns_none_when_primary_fails(mock_gemini):
    mock_gemini.side_effect = Exception("timeout")

    client = ResilientLLMClient(primary_key="key_gemini")
    assert client.generate_text("teste") is None


@patch.object(ResilientLLMClient, "_call_gemini", new_callable=AsyncMock)
async def test_llm_async_returns_none_on_failure(mock_gemini):
    mock_gemini.side_effect = Exception("erro")

    client = ResilientLLMClient(primary_key="k1")
    assert await client.generate_text_async("teste") is None


@patch.object(ResilientLLMClient, "_call_gemini", new_callable=AsyncMock)
async def test_llm_sync_dentro_de_contexto_async_retorna_none(mock_gemini):
    """generate_text() síncrono em event loop ativo → RuntimeError → None."""
    mock_gemini.return_value = _resposta_ok()

    client = ResilientLLMClient(primary_key="k1")
    # Estamos dentro de um teste async (loop rodando): asyncio.run deve falhar
    assert client.generate_text("teste") is None


@patch.object(ResilientLLMClient, "_call_gemini", new_callable=AsyncMock)
async def test_llm_async_uses_primary(mock_gemini):
    mock_gemini.return_value = _resposta_ok("async ok")

    client = ResilientLLMClient(primary_key="k1")
    result = await client.generate_text_async("teste")

    assert result is not None
    assert result.content == "async ok"
