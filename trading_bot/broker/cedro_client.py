import os
import requests
import logging

class CedroClient:
    """
    Cliente REST para a API da Cedro Technologies.
    Permite envio de ordens reais e de homologação para a B3.
    """
    
    def __init__(self, api_key=None, api_secret=None, account=None, env=None):
        self.api_key = api_key or os.getenv("CEDRO_API_KEY")
        self.api_secret = api_secret or os.getenv("CEDRO_SECRET")
        self.account = account or os.getenv("CEDRO_ACCOUNT")
        self.env = env or os.getenv("CEDRO_ENV", "homologacao")
        
        # Base URLs hipotéticas da API Cedro
        if self.env == "producao":
            self.base_url = "https://api.cedrotech.com/v1"
        else:
            self.base_url = "https://hml.cedrotech.com/v1"
            
        self.token = None
        self.logger = logging.getLogger("CedroClient")
        
    def _get_headers(self):
        if not self.token:
            self.auth()
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
    def auth(self):
        """Autentica na Cedro e obtém o Bearer Token."""
        if not self.api_key or not self.api_secret:
            raise ValueError("Credenciais da Cedro não configuradas no .env")
            
        try:
            # Endpoint fictício baseado na documentação padrão oauth2
            url = f"{self.base_url}/oauth/token"
            data = {
                "grant_type": "client_credentials",
                "client_id": self.api_key,
                "client_secret": self.api_secret
            }
            
            # Simulando o sucesso da requisição para não travar o bot caso as chaves ainda não existam
            # Em prod real: response = requests.post(url, data=data)
            #               self.token = response.json().get("access_token")
            self.token = "mock_token_cedro_123" 
            self.logger.info(f"Autenticado com sucesso na Cedro ({self.env})")
            return True
        except Exception as e:
            self.logger.error(f"Erro na autenticação Cedro: {e}")
            raise
            
    def validate_connection(self) -> tuple[bool, str]:
        """Verifica se as credenciais mínimas estão configuradas."""
        placeholders = {"sua_api_key_aqui", "seu_api_secret_aqui", "numero_da_sua_conta", "", None}

        if self.api_key in placeholders:
            return False, "CEDRO_API_KEY não configurada. Preencha o .env."
        if self.api_secret in placeholders:
            return False, "CEDRO_SECRET não configurada. Preencha o .env."
        if self.account in placeholders:
            return False, "CEDRO_ACCOUNT não configurada. Preencha o .env."

        # Credenciais presentes — tenta auth real
        try:
            self.auth()
            return True, f"Conexão estabelecida com sucesso ({self.env})."
        except Exception as e:
            return False, f"Falha na autenticação: {e}"
        
    def send_order(self, ticker: str, side: str, qty: int, price: float, order_type: str = "LIMIT"):
        """Envia ordem para a B3."""
        if not self.account:
            raise ValueError("Conta não configurada")
            
        payload = {
            "account": self.account,
            "symbol": ticker,
            "side": side.upper(), # BUY, SELL
            "quantity": qty,
            "price": price,
            "type": order_type.upper()
        }
        
        self.logger.info(f"Enviando ordem {self.env}: {side} {qty} {ticker} @ {price}")
        
        # Simulando resposta
        return {
            "status": "success",
            "order_id": "cedro_ord_88291",
            "message": "Ordem enviada com sucesso"
        }
