"""引擎注册表：新增引擎后在这里加一行。

接入顺序（对应计划里的 P1 步骤 2-5）：
  tryon            -> FashnVton        步骤 2：FASHN VTON v1.5（去掉自带的、非商用的人体分割）
  segmenter        -> BiRefNet         步骤 3
  upscaler         -> RealEsrgan       步骤 3
  turntable        -> Wan22Turntable   步骤 5（最后接入，权重最大）
  model_generator  -> ZImageTurbo      P2 阶段（预设模特库）

analyzer 不在这里：Qwen3-VL-4B 通过 llama.cpp 自带的 OpenAI 兼容 server 独立运行，
server 直接用 openai_compat_vlm 适配器调用，不经过这个 worker 进程。

每个引擎的依赖（torch 等）和权重是分步下载的，所以用惰性 import：某个引擎的依赖或权重还没装好时，
只跳过它并打印原因，worker 其余部分（health、已装好的引擎）照常工作。
"""
from __future__ import annotations

import importlib
import logging

from ..gpu import ModelManager

log = logging.getLogger("worker.engines")

# capability -> (module, class name)
REGISTRY: dict[str, tuple[str, str]] = {
    "tryon": ("fashn_vton", "FashnVton"),
    "segmenter": ("birefnet", "BiRefNet"),
    "upscaler": ("realesrgan", "RealEsrgan"),
}


def register_all(manager: ModelManager) -> None:
    for capability, (module_name, cls_name) in REGISTRY.items():
        try:
            module = importlib.import_module(f".{module_name}", __name__)
            engine_cls = getattr(module, cls_name)
            manager.register(capability, engine_cls())
            log.info("已注册 %s -> %s", capability, cls_name)
        except Exception as e:
            log.warning("跳过 %s（%s 依赖或权重还没装好）：%s", capability, module_name, e)
