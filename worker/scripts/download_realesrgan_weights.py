#!/usr/bin/env python3
"""下载 Real-ESRGAN x4plus 权重（BSD-3-Clause，官方 GitHub release）。

用法：worker\\.venv\\Scripts\\python scripts\\download_realesrgan_weights.py
"""
import os
import urllib.request

URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"
DEST_DIR = os.path.join(os.path.dirname(__file__), "..", "models", "realesrgan")


def main():
    dest_dir = os.path.abspath(DEST_DIR)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "RealESRGAN_x4plus.pth")
    print(f"下载 {URL}\n  -> {dest}")
    urllib.request.urlretrieve(URL, dest)
    print(f"完成，大小：{os.path.getsize(dest)} 字节")


if __name__ == "__main__":
    main()
