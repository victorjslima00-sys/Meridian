"""
Regressão: `AppConfig.load()` lia os YAMLs sem encoding explícito.

`open(path)` sem `encoding=` usa a codepage do sistema — cp1252 no Windows,
UTF-8 em Linux/macOS. Os arquivos de config SÃO UTF-8 e têm comentários em
português.

O bug era latente e dependia de QUAL acento alguém escrevesse: `ã`, `ç`, `é`
viram bytes que existem em cp1252 (decodificavam ERRADO, mas em silêncio); já
o `Í` é UTF-8 `\xc3\x8d`, e `\x8d` é INDEFINIDO em cp1252 — `UnicodeDecodeError`
na carga da config, derrubando ~29 testes de uma vez.

Foi exatamente o que aconteceu ao escrever "IRREPRODUZÍVEL" num comentário do
settings.yaml. O teste trava o contrato: config carrega independentemente do
acento usado e da codepage do sistema.
"""
import yaml

from trading_bot.core.config import AppConfig


class TestConfigLeEmUTF8:
    def test_carrega_config_real_do_projeto(self):
        """Guarda básica: a config do repositório carrega sem estourar."""
        cfg = AppConfig.load()
        assert cfg.get("risk", "kelly_fraction") is not None
        assert cfg.get("signals", "breakout_period") is not None

    def test_carrega_yaml_com_acento_fora_do_cp1252(self, tmp_path):
        """O caso que quebrou: caracteres cujo byte UTF-8 não existe em cp1252.
        Se este teste falhar em Windows e passar em Linux, o encoding voltou a
        ser implícito."""
        settings = tmp_path / "settings.yaml"
        universe = tmp_path / "universe.yaml"
        # Í (\xc3\x8d), Ó (\xc3\x93), Ú (\xc3\x9a) — o 2º byte de Í não existe
        # em cp1252 e é o que estourava.
        settings.write_text(
            "# IRREPRODUZÍVEL — ÓTIMO — ÚNICO\n"
            "risk:\n"
            "  kelly_fraction: 0.25\n",
            encoding="utf-8",
        )
        universe.write_text(
            "universe:\n  tickers:\n    - PETR4\n", encoding="utf-8"
        )
        cfg = AppConfig.load(str(settings), str(universe))
        assert cfg.get("risk", "kelly_fraction") == 0.25
        assert cfg.get("_universe", "tickers") == ["PETR4"]

    def test_ingestion_le_os_mesmos_yamls_em_utf8(self):
        """`ingestion._load_settings/_load_universe` leem os MESMOS arquivos que
        o AppConfig — e tinham o mesmo `open()` sem encoding. Corrigir só um
        lado deixaria o bug vivo no caminho de ingestão de dados."""
        from trading_bot.data.ingestion import _load_settings, _load_universe

        assert _load_settings()["risk"]["kelly_fraction"] is not None
        assert len(_load_universe()) > 0

    def test_nenhum_open_de_texto_sem_encoding_em_producao(self):
        """Varredura estrutural: o bug é latente e invisível no CI (Ubuntu usa
        UTF-8 por padrão). Só um teste que olha o CÓDIGO pega a reintrodução —
        um teste de comportamento passaria em Linux e falharia em Windows."""
        import ast
        from pathlib import Path

        raiz = Path(__file__).resolve().parents[1]
        infratores = []
        for py in list((raiz / "trading_bot").rglob("*.py")) + list(
            (raiz / "backend").rglob("*.py")
        ):
            arvore = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            for no in ast.walk(arvore):
                if not (isinstance(no, ast.Call) and getattr(no.func, "id", None) == "open"):
                    continue
                kwargs = {k.arg for k in no.keywords}
                if "encoding" in kwargs:
                    continue
                # modo binário não precisa de encoding
                modo = ""
                if len(no.args) > 1 and isinstance(no.args[1], ast.Constant):
                    modo = str(no.args[1].value)
                if "b" in modo:
                    continue
                infratores.append(f"{py.relative_to(raiz)}:{no.lineno}")
        assert infratores == [], (
            f"open() de texto sem encoding= (quebra em Windows/cp1252): {infratores}"
        )

    def test_settings_do_projeto_e_utf8_valido(self):
        """O arquivo em si tem de ser UTF-8 — se alguém salvar em cp1252, o
        `encoding="utf-8"` do loader passa a falhar do outro lado."""
        with open("config/settings.yaml", encoding="utf-8") as f:
            texto = f.read()
        assert yaml.safe_load(texto.replace("${", "$ {")) is not None
