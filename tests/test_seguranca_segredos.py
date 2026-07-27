"""
Tripwire: nenhum segredo pode entrar no repositório.

O repositório é PÚBLICO. Uma auditoria levantou o risco de `frontend/dist/`
(bundle buildado, que embute variáveis `VITE_*` no JavaScript em texto claro)
e `frontend/.env.local` terem sido publicados. A verificação histórica mostrou
que **não foram** — mas o que impediu isso foi `.gitignore`, e `.gitignore`
é silencioso: se alguém rodar `git add -f`, renomear o diretório de build, ou
mudar a config do Vite, o segredo vaza sem nenhum aviso.

Este teste é o alarme que faltava. Falha ANTES do commit chegar ao GitHub.

Escopo deliberado: verifica o que está RASTREADO pelo git, não o disco. Um
`.env.local` no disco é normal e esperado; rastreado, é incidente.
"""
import re
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]

# Padrões de credencial de provedores usados/previstos pelo projeto.
PADROES_SEGREDO = [
    (re.compile(r"AIza[0-9A-Za-z_\-]{30,}"), "Google/Gemini API key"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "OpenAI-style secret key"),
    (re.compile(r"\bgsk_[A-Za-z0-9]{20,}"), "Groq API key"),
    (re.compile(r"\bghp_[A-Za-z0-9]{30,}"), "GitHub personal access token"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"), "Slack token"),
    (re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_\-]{30,}"), "Telegram bot token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "chave privada"),
]

# Caminhos que NUNCA podem ser versionados: build do frontend embute as
# variáveis VITE_* no bundle, e .env* carrega credenciais reais.
CAMINHOS_PROIBIDOS = [
    re.compile(r"(^|/)dist/"),
    re.compile(r"(^|/)\.env$"),
    re.compile(r"(^|/)\.env\.(local|production|development)"),
    re.compile(r"\.local$"),
]


def _arquivos_rastreados() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=True
    )
    return [linha for linha in out.stdout.splitlines() if linha.strip()]


class TestNenhumSegredoVersionado:
    def test_nenhum_caminho_proibido_esta_rastreado(self):
        """dist/ e .env* não podem estar no índice do git. É o caso que a
        auditoria levantou: bundle do Vite carrega VITE_API_KEY em texto claro."""
        rastreados = _arquivos_rastreados()
        infratores = [
            f for f in rastreados
            if any(p.search(f) for p in CAMINHOS_PROIBIDOS)
        ]
        assert infratores == [], (
            f"Arquivos proibidos versionados: {infratores}. "
            "Rode `git rm --cached <arquivo>` e confirme o .gitignore."
        )

    def test_nenhum_arquivo_rastreado_contem_credencial(self):
        """Varre o conteúdo de tudo que está versionado. Pega o caso em que o
        segredo entra por um caminho não previsto (config, script, notebook)."""
        achados = []
        for rel in _arquivos_rastreados():
            caminho = RAIZ / rel
            if not caminho.is_file():
                continue
            try:
                texto = caminho.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for padrao, rotulo in PADROES_SEGREDO:
                if padrao.search(texto):
                    achados.append(f"{rel}: {rotulo}")
        assert achados == [], f"Credenciais em arquivos versionados: {achados}"

    def test_env_example_nao_tem_valor_real(self):
        """O template é versionado de propósito; só pode conter placeholders.
        Um `.env.example` preenchido com a chave de verdade é o vazamento mais
        fácil de cometer e o mais difícil de notar."""
        exemplo = RAIZ / ".env.example"
        if not exemplo.exists():
            pytest.skip(".env.example não existe")
        suspeitas = []
        for linha in exemplo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if linha.startswith("#") or "=" not in linha:
                continue
            chave, _, valor = linha.partition("=")
            valor = valor.strip().strip('"').strip("'")
            if not valor:
                continue
            for padrao, rotulo in PADROES_SEGREDO:
                if padrao.search(valor):
                    suspeitas.append(f"{chave.strip()}: {rotulo}")
        assert suspeitas == [], f".env.example com valores reais: {suspeitas}"

    def test_gitignore_cobre_build_e_env_do_frontend(self):
        """Defesa em profundidade: além de não estar rastreado hoje, tem de
        estar ignorado — senão um `git add .` distraído reintroduz."""
        for alvo in ("frontend/dist/assets/index.js", "frontend/.env.local", ".env"):
            r = subprocess.run(
                ["git", "check-ignore", "-q", alvo],
                cwd=RAIZ, capture_output=True, text=True,
            )
            assert r.returncode == 0, f"{alvo} NÃO está coberto pelo .gitignore"
