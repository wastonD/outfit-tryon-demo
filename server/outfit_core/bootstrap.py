"""组装运行环境：读取 .env 和 providers.yaml，创建存储、缓存、注册表和流程对象。"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .assets import AssetStore
from .cache import ResultCache
from .pipeline import OutfitPipeline
from .registry import Registry, load_builtin_providers

SERVER_ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path = SERVER_ROOT / ".env"):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def setup_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    logging.basicConfig(level=os.environ.get("OUTFIT_LOG_LEVEL", "INFO"),
                        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")


@dataclass
class Runtime:
    registry: Registry
    store: AssetStore
    cache: ResultCache
    pipeline: OutfitPipeline


def default_config_path() -> Path:
    env_path = os.environ.get("OUTFIT_CONFIG")
    if env_path:
        return Path(env_path)
    local = SERVER_ROOT / "config" / "providers.yaml"
    return local if local.exists() else SERVER_ROOT / "config" / "providers.example.yaml"


def build(config_path: str | Path | None = None, data_dir: str | Path | None = None) -> Runtime:
    load_env()
    load_builtin_providers()
    data = Path(data_dir or os.environ.get("OUTFIT_DATA", SERVER_ROOT / "data"))
    store = AssetStore(data / "assets")
    cache = ResultCache(data / "cache.sqlite3")
    registry = Registry.from_file(config_path or default_config_path(), store)
    return Runtime(registry, store, cache, OutfitPipeline(registry, store, cache))
