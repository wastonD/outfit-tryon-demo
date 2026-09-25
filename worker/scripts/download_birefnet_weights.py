#!/usr/bin/env python3
"""下载 BiRefNet 抠图模型权重（MIT，代码经 transformers 的 trust_remote_code 从官方仓库拉取）。

用法：worker\\.venv\\Scripts\\python scripts\\download_birefnet_weights.py
"""
import os

os.environ.setdefault("HF_HOME", os.path.join(os.path.dirname(__file__), "..", "models", "hf_cache"))

from transformers import AutoModelForImageSegmentation


def main():
    print(f"HF_HOME = {os.environ['HF_HOME']}")
    print("下载 BiRefNet（ZhengPeng7/BiRefNet，MIT）...")
    AutoModelForImageSegmentation.from_pretrained("ZhengPeng7/BiRefNet", trust_remote_code=True)
    print("完成。")


if __name__ == "__main__":
    main()
