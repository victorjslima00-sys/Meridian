<div align="center">
  <img src="assets/meridian_banner.jpg" alt="Meridian" width="100%">
  <h1>Meridian Trading System</h1>
  <p><strong>Pesquisa quantitativa e Paper Trading para a B3</strong></p>
</div>

> **Importante:** o Meridian executa somente **Paper Trading local**. Nenhuma ordem é enviada à Cedro ou à B3.

## Estado atual

- Backend FastAPI com workers supervisionados para entradas e saídas.
- Frontend React/Vite para acompanhamento e operação simulada.
- Persistência SQLite em modo WAL.
- Motor quantitativo, backtests, gestão de risco e circuit breaker.
- Autenticação das rotas mutáveis por API key definida exclusivamente no ambiente.
- Modos de execução definidos por `config/settings.yaml`.

## Requisitos

- Python 3.11 ou 3.12
- Node.js 22 para o frontend

## Instalação

```bash
git clone https://github.com/victorjslima00-sys/Meridian.git
cd Meridian
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Preencha os segredos no `.env`. A API não inicia sem uma `API_KEY` forte.

## Configuração operacional

A fonte de verdade é `config/settings.yaml`:

```yaml
execution:
  mode: manual  # manual | semi_auto | full_auto

risk:
  kelly_fraction: 0.25
  max_positions: 3
  max_position_fraction: 0.10

llm:
  failure_policy: hold
```

- `manual`: bloqueia novas entradas autônomas; a boleta simulada continua disponível.
- `semi_auto`: reservado para fluxo de aprovação; não autoexecuta entradas.
- `full_auto`: permite entradas autônomas, sempre em Paper Trading.
- `llm.failure_policy: hold`: falhas ou respostas inválidas da IA resultam em `HOLD`.

## Executar

Backend:

```bash
uvicorn backend.app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm ci
npm run dev
```

Por padrão, o frontend usa `/api`. Para desenvolvimento com servidores separados:

```bash
# frontend/.env.local
VITE_API_BASE_URL=http://localhost:8000/api
# Apenas em ambiente local e privado, se necessário:
VITE_API_KEY=sua-api-key-local
```

Uma chave incluída em JavaScript nunca é um segredo real. Em produção, prefira servir o painel atrás de autenticação/proxy e manter a API fora da internet pública.

## Testes

```bash
pytest tests/ --ignore=tests/e2e
pytest tests/e2e
cd frontend
npm run lint
npm run build
```

O CI executa Python 3.11/3.12, lint bloqueante, testes backend/E2E, lint e build do frontend.

## Segurança e deploy

- Nunca commitar `.env`, bancos `data/*.db*`, chaves `.pem`, logs ou `.agents/`.
- Configure no GitHub Actions: `API_KEY`, `ALLOWED_ORIGINS`, `EMERGENCY_PASSWORD`, Telegram e credenciais SSH.
- O deploy exclui segredos, bancos locais, caches, logs e dependências locais.
- A integração Cedro permanece apenas como código experimental/stub e não é usada para execução real.

## Estrutura

- `backend/app/`: API, workers e agentes operacionais.
- `trading_bot/`: dados, sinais, backtests, risco e integrações.
- `frontend/`: painel React/Vite.
- `config/`: universo e parâmetros operacionais.
- `tests/`: testes unitários, concorrência e E2E.
- `infra/aws/`: infraestrutura Terraform.
