import logging
import requests

logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

    def send_message(self, text: str) -> bool:
        """Envia mensagem pro Telegram. Retorna True se sucesso."""
        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram credentials not configured. Message not sent.")
            return False
            
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error("Failed to send Telegram message: %s", e)
            return False
