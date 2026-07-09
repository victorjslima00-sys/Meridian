import time
import os
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass

from llm_bridge.type.message import Message, Content
from llm_bridge.logic.chat_generate.chat_client_factory import create_chat_client

logger = logging.getLogger(__name__)

@dataclass
class LLMResponse:
    content: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str = "stop"

class LLMClientInterface(ABC):
    @abstractmethod
    def generate_text(self, prompt: str) -> Optional[LLMResponse]:
        pass

class ResilientLLMClient(LLMClientInterface):
    """
    Cliente LLM que agora utiliza o 'llm-bridge' open source, garantindo a
    captura de métricas (tokens, latência) de forma limpa.
    """
    def __init__(self, primary_key: str = "", fallback_key: str = ""):
        # Lê nativamente se não passado
        self.primary_key = primary_key or os.environ.get("GEMINI_API_KEY", "")
        self.fallback_key = fallback_key or os.environ.get("OPENAI_API_KEY", "")
        
    def generate_text(self, prompt: str) -> Optional[LLMResponse]:
        """Versão síncrona — para uso em scripts (fase2, fase3, etc.)."""
        try:
            return asyncio.run(self._call_gemini(prompt))
        except RuntimeError:
            # Loop já rodando — usar nest_asyncio ou avisar
            logger.error(
                "generate_text() síncrono chamado dentro de contexto async. "
                "Use await generate_text_async() em código FastAPI/async."
            )
            return None
        except Exception as e:
            logger.warning("Falha no LLM principal: %s. Tentando fallback...", e)
            try:
                return asyncio.run(self._call_fallback(prompt))
            except Exception as fe:
                logger.error("Fallback também falhou: %s", fe)
                return None

    async def generate_text_async(self, prompt: str) -> Optional[LLMResponse]:
        """Versão async — para uso em FastAPI, workers async, etc."""
        try:
            return await self._call_gemini(prompt)
        except Exception as e:
            logger.warning("Falha no LLM principal (async): %s. Tentando fallback...", e)
            try:
                return await self._call_fallback(prompt)
            except Exception as fe:
                logger.error("Fallback async também falhou: %s", fe)
                return None

    async def _call_gemini(self, prompt: str) -> LLMResponse:
        start_time = time.time()
        client = await create_chat_client(
            api_keys={"gemini": self.primary_key},
            messages=[Message(role="user", contents=[prompt])],
            model="gemini-1.5-flash",
            api_type="gemini",
            temperature=0.0,
            stream=False,
            thought=False,
            web_search=False,
            code_execution=False,
            structured_output_schema=None
        )
        response = await client.generate_non_stream_response()
        latency = (time.time() - start_time) * 1000
        
        return LLMResponse(
            content=response.text or "",
            latency_ms=latency,
            prompt_tokens=response.input_tokens or 0,
            completion_tokens=response.output_tokens or 0,
            finish_reason="stop" if not response.error else "error"
        )
        
    async def _call_fallback(self, prompt: str) -> LLMResponse:
        start_time = time.time()
        client = await create_chat_client(
            api_keys={"openai": self.fallback_key},
            messages=[Message(role="user", contents=[prompt])],
            model="gpt-4o-mini",
            api_type="openai",
            temperature=0.0,
            stream=False,
            thought=False,
            web_search=False,
            code_execution=False,
            structured_output_schema=None
        )
        response = await client.generate_non_stream_response()
        latency = (time.time() - start_time) * 1000
        
        return LLMResponse(
            content=response.text or "",
            latency_ms=latency,
            prompt_tokens=response.input_tokens or 0,
            completion_tokens=response.output_tokens or 0,
            finish_reason="stop" if not response.error else "error"
        )
