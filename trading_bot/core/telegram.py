import logging
import requests
import time

logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.bot_token = token
        self.chat_id = str(chat_id)
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

    def ask_for_approval(self, text: str, timeout_minutes: int) -> bool:
        """Envia mensagem com botões de aprovação/rejeição e aguarda resposta sincronicamente."""
        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram credentials not configured. Cannot ask for approval.")
            return False

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {"text": "Aprovar", "callback_data": "approve"},
                        {"text": "Rejeitar", "callback_data": "reject"}
                    ]
                ]
            }
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            message_data = resp.json()
            message_id = message_data.get("result", {}).get("message_id")
        except Exception as e:
            logger.error("Failed to send approval message: %s", e)
            return False

        timeout_seconds = timeout_minutes * 60
        start_time = time.time()
        offset = None

        while time.time() - start_time < timeout_seconds:
            try:
                updates_url = f"{self.base_url}/getUpdates"
                params = {"timeout": 2, "allowed_updates": ["callback_query"]}
                if offset:
                    params["offset"] = offset

                updates_resp = requests.get(updates_url, params=params, timeout=5)
                updates_resp.raise_for_status()
                updates = updates_resp.json().get("result", [])

                for update in updates:
                    offset = update["update_id"] + 1
                    if "callback_query" in update:
                        callback_query = update["callback_query"]
                        callback_data = callback_query.get("data")
                        callback_id = callback_query.get("id")
                        callback_message = callback_query.get("message", {})
                        callback_user_id = str(callback_query.get("from", {}).get("id", ""))

                        if message_id and callback_message.get("message_id") == message_id:
                            if callback_user_id != self.chat_id:
                                logger.warning("Unauthorized user %s tried to approve trade", callback_user_id)
                                continue
                                
                            answer_url = f"{self.base_url}/answerCallbackQuery"
                            requests.post(answer_url, json={"callback_query_id": callback_id}, timeout=5)

                            if callback_data == "approve":
                                return True
                            elif callback_data == "reject":
                                return False
            except Exception as e:
                logger.error("Error polling Telegram updates: %s", e)
            
            time.sleep(2)

        return False


# ---------------------------------------------------------------------------
# Alias de compatibilidade
# ---------------------------------------------------------------------------
# O módulo foi criado com o nome TelegramNotifier, mas código de produção e
# testes e2e importam TelegramClient. O alias permite ambos os nomes funcionarem.
TelegramClient = TelegramNotifier
