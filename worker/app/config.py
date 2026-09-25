"""worker 配置：环境变量或 .env（和 server/.env 相互独立）。"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

WORKER_ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path = WORKER_ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def setup_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    logging.basicConfig(level=os.environ.get("WORKER_LOG_LEVEL", "INFO"),
                        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")


@dataclass
class Settings:
    host: str
    port: int
    vram_budget_gb: float
    models_dir: Path


def load_settings() -> Settings:
    load_env()
    return Settings(
        host=os.environ.get("WORKER_HOST", "127.0.0.1"),
        port=int(os.environ.get("WORKER_PORT", "9001")),
        vram_budget_gb=float(os.environ.get("WORKER_VRAM_BUDGET_GB", "8")),
        models_dir=Path(os.environ.get("WORKER_MODELS_DIR", WORKER_ROOT / "models")),
    )


settings = load_settings()
