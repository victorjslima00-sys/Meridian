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

    def test_settings_do_projeto_e_utf8_valido(self):
        """O arquivo em si tem de ser UTF-8 — se alguém salvar em cp1252, o
        `encoding="utf-8"` do loader passa a falhar do outro lado."""
        with open("config/settings.yaml", encoding="utf-8") as f:
            texto = f.read()
        assert yaml.safe_load(texto.replace("${", "$ {")) is not None
