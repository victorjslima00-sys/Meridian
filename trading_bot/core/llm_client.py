import logging
import requests
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)

class LLMClientInterface(ABC):
    @abstractmethod
    def generate_text(self, prompt: str) -> Optional[str]:
        pass

class ResilientLLMClient(LLMClientInterface):
    """
    Cliente LLM com resiliência nativa e chaveamento de fallback automático.
    Se o provedor principal falhar por timeout ou erro, o secundário assume,
    garantindo que o comitê de IA não fique cego durante o pregão.
    """
    def __init__(self, primary_key: str, fallback_key: str):
        self.primary_key = primary_key
        self.fallback_key = fallback_key
        
    def generate_text(self, prompt: str) -> Optional[str]:
        # Tenta o modelo principal (Gemini) usando a REST API simples
        try:
            return self._call_gemini(prompt)
        except Exception as e:
            logger.warning("Falha no provedor LLM principal: %s. Acionando fallback transparente...", e)
            try:
                return self._call_fallback(prompt)
            except Exception as fallback_e:
                logger.error("Falha crítica: Provedor de fallback também falhou: %s", fallback_e)
                return None
                
    def _call_gemini(self, prompt: str) -> str:
        if not self.primary_key:
            raise ValueError("Chave do provedor principal não configurada.")
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.primary_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
        
    def _call_fallback(self, prompt: str) -> str:
        if not self.fallback_key:
            raise ValueError("Chave de fallback não configurada.")
            
        # Chamada genérica de fallback para modelo alternativo (padrão de mercado)
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.fallback_key}"
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}]
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        return data["choices"][0]["message"]["content"]
