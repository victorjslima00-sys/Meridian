from unittest.mock import patch, MagicMock
from trading_bot.core.llm_client import ResilientLLMClient

def test_llm_uses_primary_when_available():
    client = ResilientLLMClient(primary_key="key_gemini", fallback_key="key_openai")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "resposta ok"}]}}]
    }
    mock_resp.raise_for_status = MagicMock()
    with patch("requests.post", return_value=mock_resp) as mock_post:
        result = client.generate_text("teste")
    assert result == "resposta ok"
    assert mock_post.call_count == 1  # só chamou o primário

def test_llm_falls_back_when_primary_fails():
    client = ResilientLLMClient(primary_key="key_gemini", fallback_key="key_openai")
    mock_fallback = MagicMock()
    mock_fallback.json.return_value = {
        "choices": [{"message": {"content": "fallback ok"}}]
    }
    mock_fallback.raise_for_status = MagicMock()
    with patch("requests.post", side_effect=[Exception("timeout"), mock_fallback]):
        result = client.generate_text("teste")
    assert result == "fallback ok"

def test_llm_returns_none_when_both_fail():
    client = ResilientLLMClient(primary_key="k1", fallback_key="k2")
    with patch("requests.post", side_effect=Exception("erro")):
        result = client.generate_text("teste")
    assert result is None

def test_llm_empty_primary_key_raises_in_call():
    client = ResilientLLMClient(primary_key="", fallback_key="k2")
    mock_fb = MagicMock()
    mock_fb.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    mock_fb.raise_for_status = MagicMock()
    with patch("requests.post", return_value=mock_fb):
        result = client.generate_text("teste")
    assert result == "ok"  # caiu no fallback
