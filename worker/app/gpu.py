"""GPU 锁 + 按需加载/卸载：同一时刻只处理一个推理请求，已加载引擎的显存总和不超预算。

新增引擎：继承 Engine，实现 load()/unload()，在 engines/__init__.py 里 register。
"""
from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger("worker.gpu")


class Engine:
    """一个推理引擎（一个模型）。load()/unload() 负责把权重搬进/搬出显存。"""
    name: str = ""
    vram_gb: float = 0.0

    def __init__(self):
        self.loaded = False
        self.last_used = 0.0

    def load(self) -> None:
        raise NotImplementedError

    def unload(self) -> None:
        raise NotImplementedError

    def spec(self) -> dict:
        """描述这个引擎的能力（例如 tryon 的 max_garments_per_call），/v1/health 会带上。"""
        return {}


class ModelManager:
    """管理所有已注册引擎的加载状态，并提供跨请求的串行 GPU 锁。"""

    def __init__(self, vram_budget_gb: float = 8.0):
        self.vram_budget_gb = vram_budget_gb
        self._engines: dict[str, Engine] = {}
        self._lock = asyncio.Lock()

    def register(self, capability: str, engine: Engine) -> None:
        self._engines[capability] = engine

    def has(self, capability: str) -> bool:
        return capability in self._engines

    def get(self, capability: str) -> Engine:
        return self._engines[capability]

    def status(self) -> dict[str, dict]:
        return {
            key: {"loaded": e.loaded, "vram_gb": e.vram_gb, "spec": e.spec()}
            for key, e in self._engines.items()
        }

    def _loaded_vram(self, exclude: str) -> float:
        return sum(e.vram_gb for k, e in self._engines.items() if e.loaded and k != exclude)

    def _evict_for(self, capability: str) -> None:
        """卸载最久未使用的已加载引擎，直到给 capability 腾出足够显存。"""
        budget_left = self.vram_budget_gb - self._engines[capability].vram_gb
        while self._loaded_vram(exclude=capability) > budget_left:
            candidates = [(k, e) for k, e in self._engines.items() if e.loaded and k != capability]
            if not candidates:
                break
            victim_key, victim = min(candidates, key=lambda kv: kv[1].last_used)
            log.info("显存预算不够，卸载 %s 腾出空间给 %s", victim_key, capability)
            victim.unload()
            victim.loaded = False

    def _ensure_loaded(self, capability: str) -> Engine:
        engine = self._engines[capability]
        if not engine.loaded:
            self._evict_for(capability)
            log.info("加载引擎 %s（预计占用 %.1fGB 显存）", capability, engine.vram_gb)
            t0 = time.time()
            engine.load()
            engine.loaded = True
            log.info("引擎 %s 加载完成，用时 %.1fs", capability, time.time() - t0)
        engine.last_used = time.time()
        return engine

    async def run(self, capability: str, fn):
        """串行获取 GPU 锁 → 按需加载引擎 → 在线程池里跑 fn(engine)，避免阻塞事件循环。"""
        if not self.has(capability):
            raise KeyError(capability)
        async with self._lock:
            engine = await asyncio.to_thread(self._ensure_loaded, capability)
            return await asyncio.to_thread(fn, engine)
