from unittest.mock import patch, MagicMock, AsyncMock
from trading_bot.core.llm_client import ResilientLLMClient, LLMResponse

@patch("trading_bot.core.llm_client.create_chat_client")
def test_llm_uses_primary_when_available(mock_create):
    mock_client = AsyncMock()
    # Cria uma resposta mockada compativel com o q o ResilientLLM espera
    mock_response = MagicMock()
    mock_response.text = "resposta ok"
    mock_response.input_tokens = 10
    mock_response.output_tokens = 5
    mock_response.error = None
    mock_client.generate_non_stream_response.return_value = mock_response
    mock_create.return_value = mock_client
    
    client = ResilientLLMClient(primary_key="key_gemini", fallback_key="key_openai")
    result = client.generate_text("teste")
    
    assert result is not None
    assert result.content == "resposta ok"
    # Certifica de que foi chamado (1 para create_client e dps o call)
    assert mock_create.call_count == 1

@patch("trading_bot.core.llm_client.create_chat_client")
def test_llm_falls_back_when_primary_fails(mock_create):
    mock_client_fallback = AsyncMock()
    mock_response_fb = MagicMock()
    mock_response_fb.text = "fallback ok"
    mock_response_fb.input_tokens = 10
    mock_response_fb.output_tokens = 5
    mock_response_fb.error = None
    mock_client_fallback.generate_non_stream_response.return_value = mock_response_fb
    
    # Faz a primeira chamada levantar erro, e a segunda retornar o client
    mock_create.side_effect = [Exception("timeout"), mock_client_fallback]
    
    client = ResilientLLMClient(primary_key="key_gemini", fallback_key="key_openai")
    result = client.generate_text("teste")
    
    assert result is not None
    assert result.content == "fallback ok"
    assert mock_create.call_count == 2

@patch("trading_bot.core.llm_client.create_chat_client")
def test_llm_returns_none_when_both_fail(mock_create):
    mock_create.side_effect = Exception("erro")
    
    client = ResilientLLMClient(primary_key="k1", fallback_key="k2")
    result = client.generate_text("teste")
    assert result is None
