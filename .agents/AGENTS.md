# Regras do Projeto Meridian (Trading Bot B3)

As seguintes regras são INQUEBRÁVEIS e devem nortear qualquer modificação, refatoração ou criação de novos módulos no sistema.

## Regras de Ouro (Segurança e Execução)
1. **GESTÃO DE RISCO INTOCÁVEL:** O "Circuit Breaker" e a validação do "Kelly Fraction" (nunca superior a 1.0) nunca podem ser desativados, mockados de forma a ignorar falhas reais ou contornados em nenhuma atualização de código.
2. **PAPER TRADING PRIMEIRO:** Todo novo módulo de execução ou integração de corretora deve nascer operando estritamente em modo de simulação (Paper Trading) para garantir a segurança financeira do projeto antes de qualquer transação real.
3. **AUTONOMIA COM NOTIFICAÇÃO:** O robô opera de forma autônoma e silenciosa, mas DEVE notificar assincronamente as execuções realizadas para fins de auditoria (ex: Telegram).
