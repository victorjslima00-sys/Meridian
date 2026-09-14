# Primeira conexão MetaTrader 5 — demonstração

Esta entrega verifica a conexão do terminal e identifica instrumentos. É
somente leitura: **não envia, cancela ou altera ordens, nem testa execução**.
O backend e o simulador B3 continuam com o comportamento anterior.

## Preparação

1. Instale o MetaTrader 5 para Windows e conecte você mesmo uma conta demo.
2. Anote apenas o nome exato do servidor. Não coloque senha, login, token,
   telefone ou e-mail em código, comandos, relatórios ou mensagens.
3. No ambiente Python do projeto, instale `requirements-mt5.txt`.

```powershell
python -m pip install -r requirements-mt5.txt
python -m trading_bot.broker.mt5_diagnostics --terminal "C:\Program Files\MetaTrader 5\terminal64.exe" --server "NOME-EXATO-DO-SERVIDOR-DEMO"
```

Substitua o servidor pelo nome mostrado na conta conectada. O programa utiliza
a sessão do terminal; não recebe credenciais nem troca a conta via `login()`.
A biblioteca nativa pode abrir o terminal se ele estiver fechado e utilizar
a última conta salva. O diagnóstico confirma o **tipo demo informado pela API**
antes de consultar os instrumentos. Nome de servidor contendo “Demo” não basta.

## O que o resultado significa

- `ok: true`: conexão demo e metadados válidos no momento da consulta.
- `order_execution_tested: false`: nenhuma execução foi testada.
- `currency`: moeda real da conta virtual, sem conversão presumida para BRL.
- `symbols`: amostra de até 20 instrumentos, com unidade de contrato e limites
  de lote definidos pela corretora. A contagem se refere à lista completa.
- `collected_at_utc`: horário da consulta, **não horário de uma cotação**.

Não são consultados preços, posições ou histórico neste primeiro passo.
A API retorna informações completas da conta; o diagnóstico utiliza apenas
identidade interna, tipo, servidor e moeda. Saldo, patrimônio e titular não
são incluídos no relatório. Um diagnóstico bem-sucedido não prova que o feed de cotações
está atualizado, que um ativo aceita ordens ou que a estratégia é rentável.

Conta real, concurso, tipo desconhecido, servidor diferente, desconexão,
metadados inválidos ou troca detectada de conta produzem erro (saída 2) e
descartam o resultado. As leituras de identidade antes/depois não são atômicas;
não devem ser reutilizadas como autorização para uma ordem futura.

O relatório omite login, titular, senha e caminhos. Erros nativos são substituídos
por mensagens fixas. Não envia logs ao painel web, Telegram ou outro serviço,
nem grava no banco de paper trading. Se salvar relatórios, use `reports/`
(ignorado pelo Git).

## Próximas etapas

Conexão local verificada em 12/09/2026 com o servidor `XPMT5-DEMO`, tipo demo
confirmado pela API, moeda BRL e terminal build 6191. A consulta retornou
58.355 registros de instrumentos; essa contagem não implica que todos estejam
negociáveis ou atualizados. PETR4F e VALE3F foram consultados separadamente e
retornaram mínimo/passo de 1 ação, máximo de 99 e contrato de 1 unidade.
Isso descreve apenas metadados da demo, não disponibilidade/custos em conta real.

O primeiro acesso revelou que os registros nativos do SDK são tuplas que o
Pydantic rejeita em `from_attributes`. A leitura agora extrai somente os campos
necessários antes de aplicar os mesmos tipos estritos e invariantes. Os testes
reproduzem esse formato, incluindo rejeição de conta real e servidor diferente.

Depois da conta demo conectada: verificar instrumentos e cotações, implementar
controle de ordens demo com identificadores persistentes e reconciliação,
exercitar rejeições, execuções parciais e desconexões. A ligação com os sinais do
Meridian dependerá da compatibilidade dos ativos e da estratégia.

Uma demo de Forex/CFDs não valida a estratégia de ações B3 e um saldo virtual
em USD não equivale ao orçamento de R$800. Capital real exige uma avaliação
separada de corretora, custos, execução, risco e evidência da estratégia.

## Testes

```powershell
python -m pytest tests/test_mt5_diagnostics.py -q
```

Os testes usam um substituto restrito do SDK, sem acesso ao terminal ou à
corretora. A dependência MetaTrader5 só é carregada na execução explícita do CLI.

Referências oficiais:
- https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py
- https://www.mql5.com/en/docs/python_metatrader5/mt5accountinfo_py
- https://www.mql5.com/en/docs/python_metatrader5/mt5symbolsget_py
