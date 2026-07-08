import yaml
import logging
from pathlib import Path
from dataclasses import dataclass

@dataclass
class AppConfig:
    raw: dict

    @classmethod
    def load(
        cls,
        settings_path: str = "config/settings.yaml",
        universe_path: str = "config/universe.yaml",
    ) -> "AppConfig":
        import os
        import re

        with open(settings_path) as f:
            raw_text = f.read()
        
        # Expandir ${VAR_NAME} com os valores do ambiente
        def expand_env(match):
            var_name = match.group(1)
            return os.environ.get(var_name, "")  # "" se não configurada
        
        expanded = re.sub(r'\$\{([^}]+)\}', expand_env, raw_text)
        settings = yaml.safe_load(expanded)

        with open(universe_path) as f:
            universe = yaml.safe_load(f)
        settings["_universe"] = universe["universe"]
        return cls(raw=settings)

    def get(self, *keys, default=None):
        d = self.raw
        for k in keys:
            if not isinstance(d, dict) or k not in d:
                return default
            d = d[k]
        return d


def setup_logging(cfg: AppConfig) -> None:
    level_name = cfg.get("logging", "level", default="INFO")
    path = cfg.get("logging", "path", default=None)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        handlers=handlers,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
