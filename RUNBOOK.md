# RUNBOOK — Rodar o Meridian em Paper Trading contínuo (Windows)

Este documento é operacional: passo a passo exato para subir o backend
localmente e mantê-lo rodando de forma contínua em **Paper Trading**
(nenhuma ordem real é enviada — ver `CLAUDE.md`). Para instalação inicial
(venv, dependências, frontend), ver `README.md` — este runbook assume que
os passos de "Instalação" do README já foram feitos.

## 1. Pré-requisitos

- Python 3.11 ou 3.12, venv criado e `pip install -r requirements-dev.txt`
  já rodado (ver README → Instalação).
- `.env` existe na raiz (copiado de `.env.example`). Se ainda não existir:
  ```powershell
  Copy-Item .env.example .env
  ```
- Pasta `data/` existe. **Não é criada automaticamente** — sem ela, o
  primeiro boot falha com `sqlite3.OperationalError: unable to open
  database file`:
  ```powershell
  if (-not (Test-Path data)) { New-Item -ItemType Directory data }
  ```

## 2. Configurar o `.env`

Edite o `.env` (não o `.env.example`) num editor de texto — **não cole
valores de segredo no chat comigo nem em nenhum outro lugar fora do
arquivo**. Campos relevantes para rodar localmente:

| Variável | Obrigatória p/ boot? | Onde obter | O que acontece se faltar |
|---|---|---|---|
| `API_KEY` | **Sim** | Você mesmo gera (comando abaixo) | `validate_security_config()` levanta `RuntimeError` e o processo **não sobe** — fail-closed por desenho (ver `backend/app/security.py`). |
| `EMERGENCY_PASSWORD` | Não (mas recomendada) | Você mesmo gera (comando abaixo) | Boot funciona normal. `POST /api/system/emergency_stop` (fecha TODAS as posições) responde `503` — o "botão de pânico" fica indisponível até você configurar. |
| `GEMINI_API_KEY` | Não (mas é o motor de decisão) | https://aistudio.google.com/app/apikey | Ver explicação detalhada abaixo — **o bot sobe e continua protegendo posições abertas, mas nunca abre posição nova sozinho.** |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Não | `@BotFather` no Telegram (token) e `@userinfobot` ou `getUpdates` (chat id) | Boot funciona normal. Alertas (`_alerta_telegram`) falham silenciosamente — só aparecem no log do processo, você perde a notificação por Telegram. |
| `ALLOWED_ORIGINS` | Não | — | Usa o default `http://localhost:3000,http://localhost:5173`, suficiente para uso local. |

Gerar `API_KEY` e `EMERGENCY_PASSWORD` (rode duas vezes, uma para cada —
**não reuse o mesmo valor para as duas**):

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Cole cada resultado no `.env`, em `API_KEY=` e `EMERGENCY_PASSWORD=`.

Não é preciso preencher `CEDRO_*`, `BRAPI_TOKEN`, `OPENAI_API_KEY` nem
`ANTHROPIC_API_KEY` para rodar em Paper Trading local — nenhum caminho de
código ativo hoje os consulta (Cedro é stub/experimental; OpenAI/Anthropic
são fallbacks reservados, ainda não implementados — ver `BACKLOG.md`,
item P3-B).

### O que acontece exatamente sem `GEMINI_API_KEY`

`ResilientLLMClient._call_gemini` chama a API do Gemini com a chave vazia,
o que lança uma exceção — capturada internamente, `generate_text_async`
retorna `None`. `MarketAnalyst` trata qualquer resposta `None`/inválida do
LLM como falha e **sempre** retorna `signal="HOLD"` (fail-closed, decisão
já tomada no P3-A — não existe mais um fallback matemático que abriria
posição sozinho). Ou seja: com `GEMINI_API_KEY` ausente ou inválida, o
`exit_loop` continua gerenciando normalmente qualquer posição já aberta
(manual ou de antes), mas o laço de entradas nunca vai gerar um sinal
diferente de HOLD — na prática, o bot fica em modo "só protege o que já
tem, não abre nada novo sozinho" até você configurar a chave. Ordens
manuais via `POST /api/trades/execute` continuam funcionando normalmente,
pois não passam pelo LLM.

## 3. Subir a API

**Importante:** o projeto não usa `python-dotenv` — o `.env` **não é
carregado automaticamente**. É preciso injetar as variáveis na sessão do
PowerShell antes de iniciar o servidor (isso vale toda vez que abrir um
terminal novo):

```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
        $name = $matches[1].Trim()
        $value = $matches[2].Trim().Trim('"')
        [System.Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}
```

Depois, com o venv ativado (`.venv\Scripts\activate`), suba o servidor
**sem `--reload`** — `--reload` é para desenvolvimento (reinicia o
processo a cada mudança de arquivo, o que mataria o `exit_loop` no meio de
uma proteção de stop-loss ativa; use-o só quando estiver editando código,
não numa sessão pensada para rodar contínua):

```powershell
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Se `API_KEY` não estiver setada corretamente na sessão (esqueceu o passo
de carregar o `.env`, por exemplo), o processo encerra imediatamente com
`RuntimeError: API_KEY não configurada` — comportamento esperado, não é
bug.

Deixe este terminal aberto e rodando — é aqui que ficam os logs do
`exit_loop`, do laço de entradas e dos alertas.

## 4. Verificar que está saudável

Num **segundo** terminal (não feche o que está rodando o servidor):

```powershell
curl.exe http://127.0.0.1:8000/api/status
```

Esperado logo após o boot (`status` pode aparecer como `"starting"` por
uma fração de segundo antes de estabilizar):

```json
{"status":"online","worker_alive":true,"worker_status":"running",
 "last_exit_activity_at":"<timestamp recente>",
 "last_effective_exit_scan_at":"<timestamp recente>", "restart_count":0, ...}
```

- `status: "online"` — os dois laços (entrada e saída) saudáveis.
- `last_exit_activity_at` deve atualizar a cada ~5s (`exit_loop` rodando)
  — rode o `curl` duas vezes com alguns segundos de intervalo e confirme
  que o timestamp avança.
- Se aparecer `"unprotected"` ou `"stopped"`, o `exit_loop` não está
  saudável — olhe o log do primeiro terminal antes de confiar no bot com
  qualquer posição aberta.

Snapshot diário de equity (criado na primeira passada do laço de
entradas, não do laço de saída — pode levar até alguns segundos após o
boot):

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/trading_bot.db'); print(c.execute('SELECT * FROM equity_snapshots ORDER BY date DESC LIMIT 1').fetchall())"
```

Deve retornar uma linha com a data de hoje (fuso B3) e o patrimônio
calculado. Se vier vazio, aguarde mais alguns segundos e rode de novo —
só existe um snapshot por dia de pregão, então isso só falha em rodadas
seguidas no mesmo dia (aí já vai existir de uma execução anterior).

## 5. Parar com segurança

**Se o servidor está rodando em primeiro plano** (você vê os logs no
terminal): `Ctrl+C` no terminal do uvicorn. Isso dispara o shutdown do
`lifespan`, que cancela as tasks do `exit_loop` e do laço de entradas de
forma limpa (`asyncio.CancelledError` é propagado e tratado — não é um
crash, não conta para `restart_count`).

**Se você colocou o servidor em segundo plano** (via `Start-Process` ou
`&` no fim do comando): **não confie em matar pelo PID que o PowerShell/
Git Bash reportou na hora de iniciar** — descobrimos durante os testes
deste projeto que, no Git Bash sobre Windows, o PID de `$!` é o do
processo-wrapper, não o do `python.exe` real, e `kill` nele não encerra o
servidor de fato (ele continua rodando e escrevendo no banco). Confirme o
PID real pela porta antes de matar:

```powershell
$conn = Get-NetTCPConnection -LocalPort 8000 -State Listen
Stop-Process -Id $conn.OwningProcess -Force
```

Depois, confirme que a porta ficou livre:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
```

(sem saída = encerrado de verdade).

Não há necessidade de fechar posições antes de parar: é Paper Trading,
não há ordem pendente em corretora nenhuma, e o estado das posições fica
persistido no SQLite — ao subir de novo, o `exit_loop` retoma a gestão
das posições que já estavam abertas normalmente.
