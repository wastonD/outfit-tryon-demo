"""任意 OpenAI 兼容的视觉大模型：本地 llama.cpp / Ollama / vLLM，或云端通义千问、豆包、Kimi、GPT、Claude 等。

配置示例：
  qwen-local: {type: openai_compat_vlm, base_url: http://127.0.0.1:8080/v1, model: qwen3-vl-4b}
  qwen-cloud: {type: openai_compat_vlm, base_url: https://dashscope.aliyuncs.com/compatible-mode/v1,
               model: qwen-vl-max, api_key_env: DASHSCOPE_API_KEY, info: {cost_per_call: 0.01}}
可选：image_mode: url|data_uri（默认有 URL 用 URL）、temperature、timeout、extra_body、headers、
      health_check（本地地址默认开启，检查 /models 是否可访问）、
      resize_long_edge（设置后，发送前把图片长边缩放到这个像素数以内，再转成 JPEG data URI；
      本地 CPU 推理的图片 token 数和长边像素数近似线性相关）
"""
import base64
import io
import os
import time
import urllib.parse

from outfit_core.capabilities import GarmentAnalyzer, Provider, ProviderError, ProviderInfo
from outfit_core.http import HttpError, request
from outfit_core.registry import register
from outfit_core.types import Asset, GarmentAnalysis

from ._prompts import ANALYZE_PROMPT, parse_analysis


def _is_local(url: str) -> bool:
    return urllib.parse.urlparse(url).hostname in ("127.0.0.1", "localhost", "0.0.0.0", "::1")


@register("openai_compat_vlm")
class OpenAICompatVLM(Provider, GarmentAnalyzer):
    default_info = ProviderInfo(license="取决于所接模型", cost_per_call=None)

    def _api_key(self):
        env_name = self.config.get("api_key_env")
        return os.environ.get(env_name) if env_name else None

    def available(self):
        if self.config.get("api_key_env") and not self._api_key():
            return False, f"环境变量 {self.config['api_key_env']} 未设置"
        if not self.config.get("base_url") or not self.config.get("model"):
            return False, "缺少 base_url 或 model"
        if self.config.get("health_check", _is_local(self.config["base_url"])):
            return self._probe()
        return True, "ok"

    def _probe(self):
        """本地服务（llama.cpp / Ollama / vLLM）默认检查 /models 是否可访问，结果缓存 15 秒。"""
        now = time.time()
        if now - getattr(self, "_probe_at", 0) > self.config.get("health_ttl", 15):
            try:
                request("GET", self.config["base_url"].rstrip("/") + "/models", timeout=3)
                self._probe_result = (True, "ok")
            except Exception as e:
                self._probe_result = (False, f"服务无法连接：{e}")
            self._probe_at = now
        return self._probe_result

    def chat(self, content: list[dict], **kwargs) -> str:
        headers = dict(self.config.get("headers", {}))
        if key := self._api_key():
            headers["Authorization"] = f"Bearer {key}"
        body = {"model": self.config["model"], "messages": [{"role": "user", "content": content}],
                "temperature": self.config.get("temperature", 0.1), **self.config.get("extra_body", {}), **kwargs}
        url = self.config["base_url"].rstrip("/") + "/chat/completions"
        try:
            r = request("POST", url, headers, body, timeout=self.config.get("timeout", 120))
            return r["choices"][0]["message"]["content"]
        except (HttpError, KeyError, IndexError) as e:
            raise ProviderError(f"{self.name} 调用失败：{e}") from None

    def analyze(self, image: Asset) -> GarmentAnalysis:
        max_edge = self.config.get("resize_long_edge")
        if max_edge:
            img = _resized_data_uri(self.store, image, max_edge)
        else:
            mode = self.config.get("image_mode", "auto")
            img = image.url if (mode in ("auto", "url") and image.url) else self.store.to_data_uri(image)
        text = self.chat([{"type": "image_url", "image_url": {"url": img}},
                          {"type": "text", "text": ANALYZE_PROMPT}])
        return parse_analysis(text)


def _resized_data_uri(store, image: Asset, max_edge: int) -> str:
    """把图片长边缩放到 max_edge 像素以内再转成 JPEG data URI；缩放失败（非图片、损坏文件等）
    时退回原图，不阻塞识别。本地 CPU 推理下，图片 token 数随像素数增长，长边 768 左右能大幅
    缩短耗时又基本不影响识别准确率。"""
    data = store.read_bytes(image)
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
            if max(w, h) <= max_edge:
                mime = image.mime or "image/jpeg"
                return f"data:{mime};base64," + base64.b64encode(data).decode()
            scale = max_edge / max(w, h)
            im = im.convert("RGB").resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=88)
            return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        mime = image.mime or "image/jpeg"
        return f"data:{mime};base64," + base64.b64encode(data).decode()
