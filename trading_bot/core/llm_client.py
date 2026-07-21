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
    Cliente LLM com cadeia de fallback multi-provedor. Cada provedor só
    entra na cadeia se sua chave/token estiver configurado (env var ou
    passado explicitamente) — sem chave, o provedor é pulado, nunca
    chamado. Em qualquer falha (rate limit, indisponibilidade, etc.), a
    cadeia tenta o próximo provedor configurado, na ordem abaixo. Só
    retorna None se TODOS os provedores configurados falharem — o
    fail-closed de negócio (HOLD) fica no MarketAnalyst, não aqui.

    Ordem da cadeia: gemini -> groq -> cerebras -> github_models -> openai.
    Gemini primeiro por ser o provedor original; os demais em ordem de
    generosidade de cota gratuita observada (ver BACKLOG.md).
    """
    def __init__(
        self,
        primary_key: str = "",
        fallback_key: str = "",
        groq_key: str = "",
        cerebras_key: str = "",
        github_models_token: str = "",
        openai_key: str = "",
    ):
        self.primary_key = primary_key or os.environ.get("GEMINI_API_KEY", "")
        self.fallback_key = fallback_key or os.environ.get("OPENAI_API_KEY", "")
        self.groq_key = groq_key or os.environ.get("GROQ_API_KEY", "")
        self.cerebras_key = cerebras_key or os.environ.get("CEREBRAS_API_KEY", "")
        self.github_models_token = github_models_token or os.environ.get(
            "GITHUB_MODELS_TOKEN", ""
        )
        self.openai_key = openai_key or self.fallback_key

    def _provider_chain(self):
        """Lista (nome, callable async) só dos provedores com chave
        configurada, na ordem de tentativa."""
        chain = []
        if self.primary_key:
            chain.append(("gemini", self._call_gemini))
        if self.groq_key:
            chain.append(("groq", self._call_groq))
        if self.cerebras_key:
            chain.append(("cerebras", self._call_cerebras))
        if self.github_models_token:
            chain.append(("github_models", self._call_github_models))
        if self.openai_key:
            chain.append(("openai", self._call_openai))
        return chain

    def generate_text(self, prompt: str) -> Optional[LLMResponse]:
        """Versão síncrona — para uso em scripts (fase2, fase3, etc.)."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            logger.error(
                "generate_text() síncrono chamado dentro de contexto async. "
                "Use await generate_text_async() em código FastAPI/async."
            )
            return None

        try:
            return asyncio.run(self._try_chain(prompt))
        except Exception as e:
            logger.warning("Falha na cadeia de LLM: %s.", e)
            return None

    async def generate_text_async(self, prompt: str) -> Optional[LLMResponse]:
        """Versão async — para uso em FastAPI, workers async, etc."""
        return await self._try_chain(prompt)

    async def _try_chain(self, prompt: str) -> Optional[LLMResponse]:
        chain = self._provider_chain()
        if not chain:
            logger.warning("Nenhum provedor de LLM configurado (nenhuma chave presente).")
            return None
        for name, call in chain:
            try:
                return await call(prompt)
            except Exception as e:
                logger.warning(
                    "Falha no provedor %s: %s. Tentando próximo da cadeia.", name, e
                )
        logger.warning(
            "Todos os %d provedor(es) de LLM configurado(s) falharam.", len(chain)
        )
        return None

    async def _call_gemini(self, prompt: str) -> LLMResponse:
        import google.generativeai as genai

        start_time = time.time()

        genai.configure(api_key=self.primary_key)
        model = genai.GenerativeModel("gemini-3.1-flash-lite")

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

    async def _call_groq(self, prompt: str) -> LLMResponse:
        return await self._call_openai_compatible(
            base_url="https://api.groq.com/openai/v1",
            api_key=self.groq_key,
            model="llama-3.1-8b-instant",
            prompt=prompt,
        )

    async def _call_cerebras(self, prompt: str) -> LLMResponse:
        return await self._call_openai_compatible(
            base_url="https://api.cerebras.ai/v1",
            api_key=self.cerebras_key,
            model="gpt-oss-120b",
            prompt=prompt,
        )

    async def _call_github_models(self, prompt: str) -> LLMResponse:
        return await self._call_openai_compatible(
            base_url="https://models.github.ai/inference",
            api_key=self.github_models_token,
            model="openai/gpt-4o-mini",
            prompt=prompt,
        )

    async def _call_openai(self, prompt: str) -> LLMResponse:
        return await self._call_openai_compatible(
            base_url=None,
            api_key=self.openai_key,
            model="gpt-4o-mini",
            prompt=prompt,
        )

    async def _call_openai_compatible(
        self, base_url: Optional[str], api_key: str, model: str, prompt: str
    ) -> LLMResponse:
        """Chamada compartilhada por todo provedor compatível com a API da
        OpenAI (Groq, Cerebras, GitHub Models e a própria OpenAI) — só
        base_url/model mudam entre eles."""
        from openai import AsyncOpenAI

        start_time = time.time()

        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )

        latency = (time.time() - start_time) * 1000

        choice = response.choices[0]
        usage = response.usage
        prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

        return LLMResponse(
            content=choice.message.content or "",
            latency_ms=latency,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=choice.finish_reason or "stop",
        )
