"""结果缓存：同一模特、同一组服装、同一实现和选项只生成一次。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path


def make_key(*parts) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ResultCache:
    def __init__(self, db_path: str | Path):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, kind TEXT, value TEXT, created REAL)")
        self._conn.commit()

    def get(self, key: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, key: str, kind: str, value: dict):
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?)",
                               (key, kind, json.dumps(value, ensure_ascii=False), time.time()))
            self._conn.commit()

    def close(self):
        self._conn.close()
