"""本地文件存储：按内容哈希落盘，负责下载、读取和格式转换。适配器通过它拿到自己需要的输入格式。"""
from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
from pathlib import Path

from .http import fetch_bytes
from .types import Asset

EXT_OF = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "video/mp4": ".mp4",
          "image/bmp": ".bmp", "image/gif": ".gif"}


class AssetStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, data: bytes, mime: str | None = None, url: str | None = None) -> Asset:
        digest = hashlib.sha256(data).hexdigest()
        mime = mime or _sniff(data)
        path = self.root / digest[:2] / f"{digest}{EXT_OF.get(mime, '.bin')}"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return Asset(path=str(path), url=url, sha256=digest, mime=mime)

    def put_file(self, path: str | Path) -> Asset:
        path = Path(path)
        return self.put_bytes(path.read_bytes(), mimetypes.guess_type(path.name)[0])

    def put_data_uri(self, uri: str) -> Asset:
        match = re.match(r"data:([^;]+);base64,(.*)", uri, re.S)
        if not match:
            raise ValueError("不是 base64 data URI")
        return self.put_bytes(base64.b64decode(match.group(2)), match.group(1))

    def from_source(self, src: str) -> Asset:
        """用户输入的图片：URL 保留原地址（部分云接口可以直接用），本地路径则落盘。"""
        if src.startswith(("http://", "https://")):
            return Asset(url=src)
        if src.startswith("data:"):
            return self.put_data_uri(src)
        return self.put_file(src)

    def ensure_local(self, asset: Asset) -> Asset:
        """确保有本地文件（远程 URL 会被下载，结果中保留原 URL）。"""
        if asset.path and Path(asset.path).exists():
            if not asset.sha256:
                return self.put_file(asset.path).model_copy(update={"url": asset.url})
            return asset
        if not asset.url:
            raise ValueError("Asset 既没有本地文件也没有 URL")
        data, mime = fetch_bytes(asset.url)
        return self.put_bytes(data, mime if mime and mime != "application/octet-stream" else None, url=asset.url)

    def read_bytes(self, asset: Asset) -> bytes:
        return Path(self.ensure_local(asset).path).read_bytes()

    def to_data_uri(self, asset: Asset) -> str:
        local = self.ensure_local(asset)
        mime = local.mime or mimetypes.guess_type(local.path)[0] or "image/jpeg"
        return f"data:{mime};base64," + base64.b64encode(Path(local.path).read_bytes()).decode()

    def to_base64(self, asset: Asset) -> str:
        return base64.b64encode(self.read_bytes(asset)).decode()

    def save_remote(self, url: str) -> Asset:
        """下载云端生成结果（通常只保留 24 小时）并落盘。"""
        data, mime = fetch_bytes(url)
        return self.put_bytes(data, mime if mime and mime != "application/octet-stream" else None, url=url)


def _sniff(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp":
        return "video/mp4"
    if data[:2] == b"BM":
        return "image/bmp"
    return None
