import unittest
from unittest.mock import patch, MagicMock
from trading_bot.core.telegram import TelegramNotifier

class TestTelegramNotifier(unittest.TestCase):
    def setUp(self):
        self.notifier = TelegramNotifier("fake_token", "fake_chat_id")

    @patch("trading_bot.core.telegram.requests.post")
    def test_send_message_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        result = self.notifier.send_message("Hello")
        self.assertTrue(result)
        mock_post.assert_called_once()

    @patch("trading_bot.core.telegram.requests.post")
    @patch("trading_bot.core.telegram.requests.get")
    @patch("trading_bot.core.telegram.time.sleep")
    @patch("trading_bot.core.telegram.time.time")
    def test_ask_for_approval_approve(self, mock_time, mock_sleep, mock_get, mock_post):
        mock_time.side_effect = [0, 1]

        mock_post_resp = MagicMock()
        mock_post_resp.raise_for_status.return_value = None
        mock_post_resp.json.return_value = {"result": {"message_id": 123}}
        mock_post.return_value = mock_post_resp

        mock_get_resp = MagicMock()
        mock_get_resp.raise_for_status.return_value = None
        mock_get_resp.json.return_value = {
            "result": [
                {
                    "update_id": 1,
                    "callback_query": {
                        "id": "cb_1",
                        "data": "approve",
                        "message": {"message_id": 123},
                        "from": {"id": "fake_chat_id"}
                    }
                }
            ]
        }
        mock_get.return_value = mock_get_resp

        result = self.notifier.ask_for_approval("Approve order?", 1)
        
        self.assertTrue(result)
        self.assertEqual(mock_post.call_count, 2)
        mock_get.assert_called_once()

    @patch("trading_bot.core.telegram.requests.post")
    @patch("trading_bot.core.telegram.requests.get")
    @patch("trading_bot.core.telegram.time.sleep")
    @patch("trading_bot.core.telegram.time.time")
    def test_ask_for_approval_reject(self, mock_time, mock_sleep, mock_get, mock_post):
        mock_time.side_effect = [0, 1]

        mock_post_resp = MagicMock()
        mock_post_resp.json.return_value = {"result": {"message_id": 123}}
        mock_post.return_value = mock_post_resp

        mock_get_resp = MagicMock()
        mock_get_resp.json.return_value = {
            "result": [
                {
                    "update_id": 1,
                    "callback_query": {
                        "id": "cb_1",
                        "data": "reject",
                        "message": {"message_id": 123},
                        "from": {"id": "fake_chat_id"}
                    }
                }
            ]
        }
        mock_get.return_value = mock_get_resp

        result = self.notifier.ask_for_approval("Approve order?", 1)
        
        self.assertFalse(result)
        self.assertEqual(mock_post.call_count, 2)

    @patch("trading_bot.core.telegram.requests.post")
    @patch("trading_bot.core.telegram.requests.get")
    @patch("trading_bot.core.telegram.time.sleep")
    @patch("trading_bot.core.telegram.time.time")
    def test_ask_for_approval_ignora_usuario_nao_autorizado(
        self, mock_time, mock_sleep, mock_get, mock_post
    ):
        """Callback 'approve' de outro usuário (ou sem 'from') NÃO pode aprovar.

        Protege a verificação de autoria adicionada em febfb52: se ela for
        removida, este teste falha (a aprovação indevida passaria).
        """
        # 1ª iteração processa o callback intruso; depois o loop estoura o timeout.
        # side_effect como callable (não lista fixa): retorna 0, depois 1, e daí
        # em diante sempre 70. Assim o teste é imune a chamadas extras de
        # time.time() — ex.: LogRecord.__init__ chama time.time() no Python 3.11
        # (no 3.13 usa time.time_ns()), o que drenava a lista fixa e causava
        # StopIteration só no 3.11. Ver root cause no PR #3.
        _times = iter([0, 1])
        mock_time.side_effect = lambda: next(_times, 70)

        mock_post_resp = MagicMock()
        mock_post_resp.raise_for_status.return_value = None
        mock_post_resp.json.return_value = {"result": {"message_id": 123}}
        mock_post.return_value = mock_post_resp

        mock_get_resp = MagicMock()
        mock_get_resp.raise_for_status.return_value = None
        mock_get_resp.json.return_value = {
            "result": [
                {
                    "update_id": 1,
                    "callback_query": {
                        "id": "cb_1",
                        "data": "approve",
                        "message": {"message_id": 123},
                        "from": {"id": "intruso_999"}
                    }
                }
            ]
        }
        mock_get.return_value = mock_get_resp

        result = self.notifier.ask_for_approval("Approve order?", 1)

        self.assertFalse(result)
        # answerCallbackQuery não deve ser chamado: só o sendMessage inicial
        self.assertEqual(mock_post.call_count, 1)

    @patch("trading_bot.core.telegram.requests.post")
    @patch("trading_bot.core.telegram.requests.get")
    @patch("trading_bot.core.telegram.time.sleep")
    @patch("trading_bot.core.telegram.time.time")
    def test_ask_for_approval_timeout(self, mock_time, mock_sleep, mock_get, mock_post):
        mock_time.side_effect = [0, 10, 30, 70] # timeout_minutes=1 is 60s, so 70 > 60, breaks loop

        mock_post_resp = MagicMock()
        mock_post_resp.json.return_value = {"result": {"message_id": 123}}
        mock_post.return_value = mock_post_resp

        mock_get_resp = MagicMock()
        mock_get_resp.json.return_value = {"result": []}
        mock_get.return_value = mock_get_resp

        result = self.notifier.ask_for_approval("Approve order?", 1)
        
        self.assertFalse(result) # Should return False due to timeout
        self.assertEqual(mock_get.call_count, 2) # it polls while time < 60

if __name__ == "__main__":
    unittest.main()
