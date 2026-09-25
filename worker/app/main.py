"""GPU 推理 worker：实现 server/providers/remote_worker.py 里约定的 HTTP 协议。

启动：
  worker\\.venv\\Scripts\\python -m app.main
健康检查：
  curl http://127.0.0.1:9001/v1/health
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException

from . import engines
from .config import settings, setup_console
from .gpu import ModelManager
from .schemas import (AnalyzeRequest, GenerateModelRequest, SegmentRequest, TryOnRequest,
                      TurntableRequest, UpscaleRequest)

setup_console()
log = logging.getLogger("worker")

app = FastAPI(title="outfit-worker")
manager = ModelManager(vram_budget_gb=settings.vram_budget_gb)
engines.register_all(manager)


async def _run(capability: str, fn):
    try:
        return await manager.run(capability, fn)
    except KeyError:
        raise HTTPException(501, f"worker 未实现能力：{capability}") from None


@app.get("/v1/health")
async def health():
    return {"ok": True, "capabilities": manager.status()}


@app.post("/v1/analyze")
async def analyze(req: AnalyzeRequest):
    return {"analysis": await _run("analyzer", lambda e: e.run(req.image))}


@app.post("/v1/segment")
async def segment(req: SegmentRequest):
    return {"image": await _run("segmenter", lambda e: e.run(req.image, req.category))}


@app.post("/v1/tryon")
async def tryon(req: TryOnRequest):
    return {"image": await _run("tryon", lambda e: e.run(req.person, req.garments, req.options))}


@app.post("/v1/upscale")
async def upscale(req: UpscaleRequest):
    return {"image": await _run("upscaler", lambda e: e.run(req.image, req.scale))}


@app.post("/v1/turntable")
async def turntable(req: TurntableRequest):
    video, frames = await _run("turntable", lambda e: e.run(req.image, req.options))
    return {"video": video, "frames": frames}


@app.post("/v1/generate_model")
async def generate_model(req: GenerateModelRequest):
    return {"image": await _run("model_generator", lambda e: e.run(req.body, req.prompt, req.seed))}


def main():
    import uvicorn
    log.info("outfit-worker 启动，端口 %d，显存预算 %.1fGB，已注册能力：%s",
             settings.port, settings.vram_budget_gb, list(manager.status()) or "（无，等待接入模型）")
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
