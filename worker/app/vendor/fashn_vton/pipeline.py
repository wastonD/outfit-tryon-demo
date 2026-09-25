"""TryOn Pipeline — fork of fashn-ai/fashn-vton-1.5 with FashnHumanParser removed.

改动（对照上游 src/fashn_vton/pipeline.py，Apache-2.0 第 4(b) 条要求声明改动）：
  - 不再 import、加载或调用 fashn_human_parser.FashnHumanParser：它的权重继承自
    NVIDIA SegFormer 的许可证，只能非商用，和本项目的商用目标冲突（见 LICENSES.md）。
  - 去掉了 `segmentation_free` 参数：person 图现在永远是"不做人体分割"的模式，因为
    没有分割模型可用。
  - `category` 不再用于查分割标签，只用于 TryOnModel 的类别条件（CATEGORY_TO_LABEL）。
  - `garment_photo_type` 保留：它只影响要不要对服装图跑姿态检测（DWPose，Apache-2.0，
    和人体分割无关），"flat-lay" 用占位关键点，"model" 才跑真实姿态检测。
  - TryOnModel（tryon_mmdit.py）、DWPose（dwpose/）本体未改动。

来源：https://github.com/fashn-AI/fashn-vton-1.5
Pinned commit: 7c0f10af3f91ad4048fe9729c470a13ef905d25a
"""

import logging
import os
from dataclasses import dataclass
from typing import List, Literal, Optional

import cv2
import numpy as np
import torch
from PIL import Image
from tqdm.auto import tqdm

from .dwpose import DWposeDetector, draw_pose
from .preprocessing import AspectPreserveResize, ResizePad, create_clothing_agnostic_image, create_garment_image
from .tryon_mmdit import TryOnModel
from .utils import (
    get_dummy_dw_keypoints,
    get_rf_schedule,
    load_checkpoint,
    normalize_uint8_to_neg1_1,
    numpy_to_torch,
    setup_logger,
    tensor_to_pil,
)


@dataclass
class PipelineOutput:
    """Pipeline output container."""

    images: List[Image.Image]


class TryOnPipeline:
    """
    TryOn inference pipeline（不含人体分割）。

    Args:
        weights_dir: Directory containing model weights (model.safetensors, dwpose/)
        device: Device to run on ('cuda', 'cpu', or None for auto-detect)
        logger: Optional logger instance

    Example:
        pipeline = TryOnPipeline(weights_dir="./weights")
        result = pipeline(person_image, garment_image, category="tops")
    """

    CATEGORY_TO_LABEL = {"tops": 1, "bottoms": 2, "one-pieces": 3}

    def __init__(
        self,
        weights_dir: str,
        device: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.weights_dir = os.path.abspath(weights_dir)
        self.logger = logger or setup_logger("TryOnPipeline", level=logging.INFO)

        # Setup device
        self.device = torch.device(device if device else ("cuda" if torch.cuda.is_available() else "cpu"))
        self.logger.info(f"Using device: {self.device}")

        # Setup inference dtype
        self.inference_dtype = torch.float32
        if self.device.type == "cuda" and torch.cuda.is_bf16_supported():
            self.inference_dtype = torch.bfloat16
        self.logger.info(f"Using dtype: {self.inference_dtype}")

        # Validate weights exist
        self._validate_weights()

        # Load models（没有人体分割模型）
        self._setup_tryon_model()
        self._setup_pose_model()

        # Setup transforms (derived from model input shape)
        h, w = self.tryon_model.input_shape
        max_dim = max(h, w)
        self.pre_resize = AspectPreserveResize(target_size=(max_dim, max_dim), mode="fit", backend="pil")
        self.resize_pad_fn = ResizePad((w, h), backend="opencv")

    def _validate_weights(self):
        """Check that required weight files exist."""
        tryon_path = os.path.join(self.weights_dir, "model.safetensors")
        dwpose_dir = os.path.join(self.weights_dir, "dwpose")
        yolox_path = os.path.join(dwpose_dir, "yolox_l.onnx")
        dwpose_path = os.path.join(dwpose_dir, "dw-ll_ucoco_384.onnx")

        missing = []
        if not os.path.exists(tryon_path):
            missing.append(tryon_path)
        if not os.path.exists(yolox_path):
            missing.append(yolox_path)
        if not os.path.exists(dwpose_path):
            missing.append(dwpose_path)

        if missing:
            raise FileNotFoundError(
                "Missing model weights:\n" + "\n".join(f"  - {p}" for p in missing)
            )

    def _setup_tryon_model(self):
        """Load the TryOn model."""
        model_path = os.path.join(self.weights_dir, "model.safetensors")
        self.logger.info(f"Loading TryOnModel from {model_path}")

        self.tryon_model = TryOnModel()
        state_dict = load_checkpoint(model_path, device=str(self.device))
        self.tryon_model.load_state_dict(state_dict)
        self.tryon_model.to(self.device, dtype=self.inference_dtype).eval()

        self.logger.info("TryOnModel loaded")

    def _setup_pose_model(self):
        """Load DWPose model."""
        dwpose_dir = os.path.join(self.weights_dir, "dwpose")
        self.logger.info(f"Loading DWPose from {dwpose_dir}")

        dwpose_device = f"cuda:{self.device.index or 0}" if self.device.type == "cuda" else "cpu"
        self.pose_model = DWposeDetector(checkpoints_dir=dwpose_dir, device=dwpose_device)

        self.logger.info("DWPose loaded")

    @torch.inference_mode()
    def _sample(
        self,
        *,
        ca_images: torch.Tensor,
        garment_images: torch.Tensor,
        person_poses: torch.Tensor,
        garment_poses: torch.Tensor,
        garment_categories: torch.Tensor,
        num_timesteps: int = 30,
        time_shift_mu: float = 1.5,
        guidance_scale: float = 1.5,
        skip_cfg_last_n_steps: int = 1,
        use_tqdm: bool = True,
    ) -> List[Image.Image]:
        """Euler sampling with CFG."""
        device, dtype = ca_images.device, ca_images.dtype
        batch_size = ca_images.shape[0]

        # Init noisy images
        c, h, w = self.tryon_model.channels_in, *self.tryon_model.input_shape
        images = torch.randn((batch_size, c, h, w), dtype=dtype, device=device)

        # Time schedule (from 0 -> 1)
        timesteps = get_rf_schedule(num_steps=num_timesteps, mu=time_shift_mu)

        model_kwargs = {
            "person_poses": person_poses,
            "garment_poses": garment_poses,
            "ca_images": ca_images,
            "garment_images": garment_images,
            "garment_categories": garment_categories,
        }

        # Euler sampling loop
        for step_idx, (t_curr, t_prev) in enumerate(
            tqdm(
                zip(timesteps[:-1], timesteps[1:]),
                desc="Sampling",
                total=len(timesteps) - 1,
                disable=not use_tqdm,
            )
        ):
            dt = t_prev - t_curr
            t_vec = torch.full((batch_size,), t_curr, dtype=dtype, device=device)

            pred = self.tryon_model.forward_for_cfg(images, t_vec, **model_kwargs)
            v_c, v_u = pred["v_c"], pred["v_u"]

            # Skip CFG at final steps to prevent color saturation
            if skip_cfg_last_n_steps > 0 and step_idx >= num_timesteps - skip_cfg_last_n_steps:
                v_guided = v_c
            else:
                v_guided = v_u + guidance_scale * (v_c - v_u)

            images = images + dt * v_guided

        images = images.to(dtype=torch.float).clamp_(-1.0, 1.0)
        return [tensor_to_pil(img, unnormalize=True) for img in images]

    @torch.inference_mode()
    def __call__(
        self,
        person_image: Image.Image,
        garment_image: Image.Image,
        category: Literal["tops", "bottoms", "one-pieces"],
        garment_photo_type: Literal["model", "flat-lay"] = "flat-lay",
        num_samples: int = 1,
        num_timesteps: int = 30,
        guidance_scale: float = 1.5,
        skip_cfg_last_n_steps: int = 1,
        seed: int = 42,
    ) -> PipelineOutput:
        """
        Run virtual try-on inference（永远 segmentation-free，没有人体分割模型可用）。

        Args:
            person_image: RGB image of the person to dress.
            garment_image: RGB image of the garment (model photo or flat-lay).
            category: Garment category - "tops", "bottoms", or "one-pieces".
            garment_photo_type: "model" if garment is worn by a person（会跑姿态检测），
                "flat-lay" for product shots on plain backgrounds（用占位关键点）。
                本项目里服装图在到达这里之前已经用 BiRefNet 抠成了 flat-lay，默认就是它。
            num_samples: Number of output images to generate (1-4).
            num_timesteps: Diffusion sampling steps. Higher = better quality, slower.
                Recommended: 20 (fast), 30 (balanced), 50 (quality).
            guidance_scale: Classifier-free guidance strength.
            skip_cfg_last_n_steps: Skip CFG for final N steps to prevent color saturation.
            seed: Random seed for reproducibility.

        Returns:
            PipelineOutput with `images` list containing generated PIL Images.
        """
        # Set seed
        torch.manual_seed(seed)
        if self.device.type == "cuda":
            torch.cuda.manual_seed_all(seed)
        np.random.seed(seed)

        # Pre-resize for pose detection quality
        person_image = self.pre_resize(person_image, allow_upsampling=False)
        garment_image = self.pre_resize(garment_image, allow_upsampling=False)

        person_image_np = np.array(person_image)
        garment_image_np = np.array(garment_image)

        # Pose detection (DWPose expects BGR)
        person_pose = self.pose_model(person_image_np[..., ::-1])
        garment_pose = (
            get_dummy_dw_keypoints()
            if garment_photo_type == "flat-lay"
            else self.pose_model(garment_image_np[..., ::-1])
        )

        person_pose_img = draw_pose(person_pose, person_image_np.shape[0], person_image_np.shape[1], grayscale=True)
        garment_pose_img = draw_pose(garment_pose, garment_image_np.shape[0], garment_image_np.shape[1], grayscale=True)

        # 没有人体分割：person 图原样当作 clothing-agnostic 图，garment 图原样当作已抠图
        ca_image = create_clothing_agnostic_image(img_np=person_image_np.copy())
        garment_image_processed = create_garment_image(img_np=garment_image_np)

        # Resize/pad for model input
        ca_image = self.resize_pad_fn(ca_image, mem_padding=True)
        garment_image_processed = self.resize_pad_fn(garment_image_processed)
        person_pose_img = self.resize_pad_fn(person_pose_img, interpolation=cv2.INTER_NEAREST_EXACT)
        garment_pose_img = self.resize_pad_fn(garment_pose_img, interpolation=cv2.INTER_NEAREST_EXACT)

        # Prepare tensors
        def prepare_tensor(img: np.ndarray) -> torch.Tensor:
            t = numpy_to_torch(img).unsqueeze(0)
            t = normalize_uint8_to_neg1_1(t)
            t = t.to(self.device).repeat(num_samples, 1, 1, 1)
            return t

        ca_tensor = prepare_tensor(ca_image)
        garment_tensor = prepare_tensor(garment_image_processed)
        person_pose_tensor = prepare_tensor(person_pose_img)
        garment_pose_tensor = prepare_tensor(garment_pose_img)

        garment_categories = (
            torch.tensor(self.CATEGORY_TO_LABEL[category]).unsqueeze(0).repeat(num_samples).to(self.device)
        )

        # Cast to inference dtype
        ca_tensor = ca_tensor.to(dtype=self.inference_dtype)
        garment_tensor = garment_tensor.to(dtype=self.inference_dtype)
        person_pose_tensor = person_pose_tensor.to(dtype=self.inference_dtype)
        garment_pose_tensor = garment_pose_tensor.to(dtype=self.inference_dtype)

        # Run sampling
        self.logger.info(f"Running inference with {num_timesteps} timesteps...")
        images = self._sample(
            ca_images=ca_tensor,
            garment_images=garment_tensor,
            person_poses=person_pose_tensor,
            garment_poses=garment_pose_tensor,
            garment_categories=garment_categories,
            num_timesteps=num_timesteps,
            guidance_scale=guidance_scale,
            skip_cfg_last_n_steps=skip_cfg_last_n_steps,
        )

        # Unpad outputs
        images = [self.resize_pad_fn.unpad(img) for img in images]

        self.logger.info(f"Generated {len(images)} images")

        return PipelineOutput(images=images)
