"""FASHN VTON v1.5 试衣引擎。已去掉 FASHN Human Parser（NVIDIA SegFormer 非商用许可），
详见 ../vendor/fashn_vton/NOTICE.md。

装这个引擎需要的额外依赖（不在 worker/requirements.txt 里，见 worker/README.md）：
  torch torchvision --index-url https://download.pytorch.org/whl/cu121
  einops safetensors onnxruntime-gpu opencv-python matplotlib huggingface_hub

权重放在 settings.models_dir/fashn_vton/（model.safetensors + dwpose/*.onnx）。
"""
from __future__ import annotations

import gc
import logging

from ..config import settings
from ..gpu import Engine
from ..imageio import pil_to_ref, ref_to_pil
from ..schemas import GarmentRef, Ref
from ..vendor.fashn_vton import TryOnPipeline

log = logging.getLogger("worker.fashn_vton")

# 我们的 Category（top/outer/bottom/skirt/dress）→ FASHN 的三分类。
CATEGORY_MAP = {
    "top": "tops",
    "outer": "tops",
    "bottom": "bottoms",
    "skirt": "bottoms",
    "dress": "one-pieces",
}


class FashnVton(Engine):
    name = "fashn-vton-1.5"
    vram_gb = 7.0  # 972M 参数 bf16 + DWPose(onnxruntime-gpu)；8GB 卡上算"大模型"，独占预算

    def __init__(self):
        super().__init__()
        self.weights_dir = settings.models_dir / "fashn_vton"
        self._pipeline: TryOnPipeline | None = None

    def spec(self) -> dict:
        return {"max_garments_per_call": 1, "supports_layering": True, "categories": sorted(CATEGORY_MAP)}

    def load(self) -> None:
        self._pipeline = TryOnPipeline(weights_dir=str(self.weights_dir))

    def unload(self) -> None:
        import torch

        self._pipeline = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def run(self, person: Ref, garments: list[GarmentRef], options: dict) -> Ref:
        if len(garments) != 1:
            raise ValueError(f"fashn-vton 每次调用只能试一件（max_garments_per_call=1），收到 {len(garments)} 件")
        garment = garments[0]
        category = CATEGORY_MAP.get(garment.category)
        if category is None:
            raise ValueError(f"fashn-vton 不支持的服装类型：{garment.category}")

        person_image = ref_to_pil(person)
        garment_image = ref_to_pil(garment.image)
        extra = options.get("extra") or {}
        seed = options.get("seed")

        result = self._pipeline(
            person_image=person_image,
            garment_image=garment_image,
            category=category,
            garment_photo_type=extra.get("garment_photo_type", "flat-lay"),
            num_samples=1,
            num_timesteps=extra.get("num_timesteps", 30),
            guidance_scale=extra.get("guidance_scale", 1.5),
            seed=seed if seed is not None else 42,
        )
        return pil_to_ref(result.images[0])
