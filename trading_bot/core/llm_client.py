import time
import os
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass

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
    Cliente LLM nativo usando google-generativeai.
    """
    def __init__(self, primary_key: str = "", fallback_key: str = ""):
        self.primary_key = primary_key or os.environ.get("GEMINI_API_KEY", "")
        self.fallback_key = fallback_key or os.environ.get("OPENAI_API_KEY", "")
        
    def generate_text(self, prompt: str) -> Optional[LLMResponse]:
        """Versão síncrona — para uso em scripts (fase2, fase3, etc.)."""
        try:
            return asyncio.run(self._call_gemini(prompt))
        except RuntimeError:
            logger.error(
                "generate_text() síncrono chamado dentro de contexto async. "
                "Use await generate_text_async() em código FastAPI/async."
            )
            return None
        except Exception as e:
            logger.warning("Falha no LLM principal: %s.", e)
            return None

    async def generate_text_async(self, prompt: str) -> Optional[LLMResponse]:
        """Versão async — para uso em FastAPI, workers async, etc."""
        try:
            return await self._call_gemini(prompt)
        except Exception as e:
            logger.warning("Falha no LLM principal (async): %s.", e)
            return None

    async def _call_gemini(self, prompt: str) -> LLMResponse:
        import google.generativeai as genai
        
        start_time = time.time()
        
        genai.configure(api_key=self.primary_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        # O generate_content_async permite chamadas não-bloqueantes
        response = await model.generate_content_async(prompt)
        
        latency = (time.time() - start_time) * 1000
        
        prompt_tokens = 0
        completion_tokens = 0
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            prompt_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0)
            completion_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0)
        
        return LLMResponse(
            content=response.text or "",
            latency_ms=latency,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason="stop"
        )
