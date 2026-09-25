"""Ref（data_uri / url）与 PIL.Image 之间的转换，供各引擎复用。"""
from __future__ import annotations

import base64
import io

import httpx
from PIL import Image

from .schemas import Ref


def ref_to_pil(ref: Ref) -> Image.Image:
    if ref.data_uri:
        _, _, b64 = ref.data_uri.partition(",")
        return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    resp = httpx.get(ref.url, timeout=60)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGB")


def pil_to_ref(image: Image.Image, fmt: str = "PNG") -> Ref:
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    mime = f"image/{fmt.lower()}"
    return Ref(data_uri=f"data:{mime};base64,{b64}")
