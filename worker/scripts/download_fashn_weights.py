#!/usr/bin/env python3
"""下载 FASHN VTON v1.5 需要的权重（不含人体分割，那个模型完全没有用到）。

用法：worker\\.venv\\Scripts\\python scripts\\download_fashn_weights.py
"""
import os

from huggingface_hub import hf_hub_download

WEIGHTS_DIR = os.path.join(os.path.dirname(__file__), "..", "models", "fashn_vton")


def main():
    weights_dir = os.path.abspath(WEIGHTS_DIR)
    dwpose_dir = os.path.join(weights_dir, "dwpose")
    os.makedirs(dwpose_dir, exist_ok=True)

    print(f"下载到：{weights_dir}\n")

    print("下载 TryOnModel 权重（model.safetensors，~1.94GB）...")
    hf_hub_download(repo_id="fashn-ai/fashn-vton-1.5", filename="model.safetensors", local_dir=weights_dir)

    for filename in ("yolox_l.onnx", "dw-ll_ucoco_384.onnx"):
        print(f"下载 DWPose/{filename}...")
        hf_hub_download(repo_id="fashn-ai/DWPose", filename=filename, local_dir=dwpose_dir)

    print("\n完成。不下载、也不依赖 FASHN Human Parser。")


if __name__ == "__main__":
    main()
