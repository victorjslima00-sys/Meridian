---
description: Politica de tolerancia zero com vazamento de segredos, credenciais e chaves de API.
globs: ["**/*"]
always_on: true
---

# Governanca Institucional Meridian — Seguranca de Segredos

## 1. Tolerancia Zero com Exposicao de Credenciais
E terminantemente proibido versionar, registrar em logs, expor em relatorios ou incluir em arquivos rastreados pelo Git qualquer informacao sensivel, incluindo:
- Arquivos `.env`, `.env.*` (exceto `.env.example` higienizado com valores dummy);
- Chaves de API (Google Gemini, Anthropic Claude, OpenAI, Groq, etc.);
- Tokens de bots (Telegram, Slack, Discord);
- Chaves privadas SSH (`id_rsa`, `.pem`, `.p12`);
- Senhas, hashes de autenticacao e credenciais de banco de dados;
- Credenciais de corretoras (Cedro, MetaTrader 5, XP, BTG);
- Segredos de CI/CD e credenciais de cloud providers (AWS, GCP, Azure);
- Cookies de sessao ou headers de autenticacao com Bearer tokens reais.

## 2. Diretrizes de Prevencao
- O arquivo `.env.example` DEVE conter estritamente nomes de variaveis e placeholders genericos (ex: `sua_chave_aqui`).
- O teste `tests/test_seguranca_segredos.py` deve ser executado e mantido 100% verde antes de qualquer commit.
- Caso o agente precise verificar variaveis de ambiente, deve utilizar APIs de leitura segura do sistema operacional sem nunca imprimir os valores secretos na tela.

## 3. Modelo de Ameaca e Segredos de Producao (NEXUS-000D)
- **PRODUCTION SECRETS MUST NOT BE PRESENT IN THE AGENT-ACCESSIBLE DEVELOPMENT WORKSPACE.**
- O ambiente de desenvolvimento acessivel a agentes de IA (Antigravity e subagentes) NUNCA deve conter segredos, tokens ou chaves de producao.
- Ambientes de producao devem utilizar exclusivamente GitHub Environment Secrets, GitHub Actions Secrets ou gerenciador de segredos em nuvem aprovado.
- Quaisquer credenciais presentes no ambiente local de desenvolvimento devem ser estritamente de ambiente de desenvolvimento/paper trading, revogaveis, de privilegio minimo e sem capacidade de movimentar capital financeiro real.
- O PreToolUse guard e filtros de comandos shell fornecem **defesa em profundidade** (defense-in-depth), e **NAO** constituem sandbox absoluta contra execucao arbitraria de interpretadores.
