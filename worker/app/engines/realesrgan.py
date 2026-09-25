"""Real-ESRGAN x4plus 超分引擎（BSD-3-Clause）。

用 spandrel（MIT，架构代码继承原模型许可证）加载官方 .pth 权重，而不是官方 realesrgan pip 包：
那个包依赖 basicsr，basicsr 会 import 新版 torchvision 里已经删掉的
`torchvision.transforms.functional_tensor`，在这台机器的 torchvision 版本下装不上/跑不起来。
spandrel 是社区广泛使用的替代方案，加载的是同一份官方权重，依赖更干净。

权重固定是 4x（RRDBNet 架构），scale 请求 2x 时用 Lanczos 从 4x 结果降采样得到。
没做分块（tiling），超大图可能爆显存——这个模型很小，暂时够用，以后需要再加。
"""
from __future__ import annotations

import gc
import logging

import numpy as np
from PIL import Image

from ..config import settings
from ..gpu import Engine
from ..imageio import pil_to_ref, ref_to_pil
from ..schemas import Ref

log = logging.getLogger("worker.realesrgan")


class RealEsrgan(Engine):
    name = "realesrgan-x4plus"
    vram_gb = 1.5

    def __init__(self):
        super().__init__()
        self.weights_path = settings.models_dir / "realesrgan" / "RealESRGAN_x4plus.pth"
        self._model = None

    def spec(self) -> dict:
        return {"native_scale": 4}

    def load(self) -> None:
        from spandrel import ImageModelDescriptor, ModelLoader

        model = ModelLoader().load_from_file(str(self.weights_path))
        assert isinstance(model, ImageModelDescriptor)
        self._model = model.cuda().eval()

    def unload(self) -> None:
        import torch

        self._model = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def run(self, image: Ref, scale: int = 2) -> Ref:
        import torch

        pil_image = ref_to_pil(image)
        arr = np.array(pil_image).astype(np.float32) / 255.0
        tensor = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).cuda()

        with torch.no_grad():
            output = self._model(tensor)

        out_arr = (output.squeeze(0).permute(1, 2, 0).clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)
        upscaled = Image.fromarray(out_arr)  # 固定 4x

        if scale != 4:
            target = (pil_image.width * scale, pil_image.height * scale)
            upscaled = upscaled.resize(target, Image.LANCZOS)

        return pil_to_ref(upscaled, fmt="PNG")
