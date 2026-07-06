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
        with open(settings_path) as f:
            settings = yaml.safe_load(f)
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
