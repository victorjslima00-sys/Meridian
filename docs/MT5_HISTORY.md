# Histórico diário demo para pesquisa

Execute no Python Windows do projeto, com a conta demo conectada:

```powershell
python -m trading_bot.broker.mt5_history --terminal "C:\Program Files\MetaTrader 5\terminal64.exe" --server XPMT5-DEMO --symbols PETR4 PETR4F VALE3 VALE3F --start 2025-09-01 --end 2026-09-11 --output reports/historico-novo.json
```

Use nome de saída novo: arquivos existentes não são sobrescritos. Datas solicitadas em UTC, inclusivas; o dia corrente é recusado. O JSON registra datas efetivamente retornadas, quantidade de barras e volumes reais zerados, além das barras D1. Volume de ticks e volume real são preservados separadamente.

Coleta exclusivamente para pesquisa, sem login, envio de ordens, seleção de ativos, backend ou alteração do capital/configuração. Reutiliza as verificações de identidade demo/servidor do diagnóstico antes/depois da leitura. Essas verificações não são atômicas e não autorizam operações futuras.

Sem dados, conta inesperada, valores inválidos ou falha de desconexão descartam o lote inteiro. Histórico parcial não é preenchido ou considerado completo. A política de ajustes por proventos é desconhecida; calendário, atualidade, fontes cruzadas e completude ainda exigem validação. `ready_for_backtest` permanece falso.

Referência: https://www.mql5.com/pt/docs/python_metatrader5/mt5copyratesrange_py

Em 13/09/2026 a tentativa local não conectou ao terminal. Não foi coletado histórico nessa tentativa. Relatório em `reports/mt5-history-20260913.json`, ignorado pelo Git.

Após reabrir o terminal em 13/09/2026, a coleta funcionou: 258 barras por código
para PETR4, PETR4F, VALE3 e VALE3F, de 01/09/2025 a 11/09/2026, em
`reports/mt5-history-20260913-reconnected.json`. A auditoria descritiva encontrou
as mesmas datas nos quatro códigos, sem duplicatas ou volumes zerados. Há
divergências de fechamento entre normal/fracionário de até 8,7449% em PETR4
e 7,7601% em VALE3. A causa não foi determinada: não tratar como spread ou
oportunidade executável. Ajustes e comparação com fonte independente continuam
pendentes; `ready_for_backtest` permanece falso.
