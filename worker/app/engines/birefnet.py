"""BiRefNet 抠图引擎（MIT，代码和权重都可商用）。

用 transformers 的 trust_remote_code=True 加载官方仓库 ZhengPeng7/BiRefNet 的模型代码和权重，
这是该模型官方文档推荐的标准用法，不是我们自己写的推理代码。

额外依赖（不在 worker/requirements.txt 基础列表里，见 worker/README.md）：
  transformers timm kornia scipy scikit-image accelerate
"""
from __future__ import annotations

import gc
import logging

from PIL import Image
from torchvision import transforms

from ..config import settings
from ..gpu import Engine
from ..imageio import pil_to_ref, ref_to_pil
from ..schemas import Ref

log = logging.getLogger("worker.birefnet")

_TRANSFORM = transforms.Compose([
    transforms.Resize((1024, 1024)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


class BiRefNet(Engine):
    name = "birefnet"
    vram_gb = 2.0  # 0.2B 参数，fp16 权重 + 1024x1024 推理时的激活值

    def __init__(self):
        super().__init__()
        self._model = None

    def spec(self) -> dict:
        return {}

    def load(self) -> None:
        import torch
        from transformers import AutoModelForImageSegmentation

        self._model = AutoModelForImageSegmentation.from_pretrained(
            "ZhengPeng7/BiRefNet", trust_remote_code=True, cache_dir=str(settings.models_dir / "hf_cache"))
        self._model.to("cuda").eval().half()

    def unload(self) -> None:
        import torch

        self._model = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def run(self, image: Ref, category: str) -> Ref | None:
        import torch

        pil_image = ref_to_pil(image)
        input_tensor = _TRANSFORM(pil_image).unsqueeze(0).to("cuda").half()

        with torch.no_grad():
            mask = self._model(input_tensor)[-1].sigmoid().cpu()

        mask_pil = transforms.ToPILImage()(mask[0].squeeze()).resize(pil_image.size)
        cutout = pil_image.convert("RGBA")
        cutout.putalpha(mask_pil)
        return pil_to_ref(cutout, fmt="PNG")
