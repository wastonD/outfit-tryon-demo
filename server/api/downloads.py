"""下载用户提供的图片 URL，带上 Referer 和浏览器 UA（沿用 outfit_core.http 的写法，但需要自定义请求头）。"""
from __future__ import annotations

import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")


def fetch_image(url: str, referer: str | None = None, timeout: float = 60) -> tuple[bytes, str | None]:
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), resp.headers.get_content_type()
