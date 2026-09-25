"""Clothing-agnostic image creation — 已去掉基于人体分割的版本。

上游 fashn-vton-1.5 用 fashn_human_parser（权重继承 NVIDIA SegFormer 非商用许可，
见 ../../../../LICENSES.md）生成分割掩码，用来决定 inpainting 区域。我们完全不用：
person 图始终跑 segmentation-free 模式，garment 图始终当作已经抠好的 flat-lay 图
（抠图交给 BiRefNet，见 engines/birefnet.py，在调用这个引擎之前完成），所以这里
从不加载、也从不调用任何人体分割模型。这两个函数保留原来的调用签名，只是变成
直接返回原图的空操作，方便以后需要时接回一个允许商用的分割器。
"""
import numpy as np


def create_garment_image(img_np: np.ndarray, **_ignored) -> np.ndarray:
    return img_np


def create_clothing_agnostic_image(img_np: np.ndarray, **_ignored) -> np.ndarray:
    return img_np
