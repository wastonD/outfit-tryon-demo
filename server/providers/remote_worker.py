"""远程推理进程适配器：调用 worker/（本地 GPU 或租用的 GPU 服务器）上的开源模型。

主服务只认这个 HTTP 协议，模型跑在哪台机器上只取决于配置里的 url。

协议（JSON）：
  GET  /v1/health               → {"ok": true, "capabilities": {"tryon": {"spec": {...}}, ...}}
  POST /v1/analyze              {"image": Ref}                              → {"analysis": {...}}
  POST /v1/segment              {"image": Ref, "category": "top"}           → {"image": Ref | null}
  POST /v1/tryon                {"person": Ref, "garments": [{"id","category","image": Ref}], "options": {...}}
                                                                             → {"image": Ref}
  POST /v1/upscale              {"image": Ref, "scale": 2}                  → {"image": Ref}
  POST /v1/turntable            {"image": Ref, "options": {...}}            → {"video": Ref | null, "frames": [Ref]}
  POST /v1/generate_model       {"body": {...}, "prompt": "...", "seed": 1} → {"image": Ref}
  Ref = {"data_uri": "data:image/png;base64,..."} 或 {"url": "http://..."}

配置示例：
  fashn-local: {type: remote_worker, url: http://127.0.0.1:9001, capabilities: [tryon],
                spec: {max_garments_per_call: 1}, timeout: 600,
                info: {commercial_ok: true, license: Apache-2.0, cost_per_call: 0, uses_gpu: true, vram_gb: 8}}
"""
import time

from outfit_core.capabilities import (GarmentAnalyzer, GarmentSegmenter, ModelImageGenerator, Provider,
                                      ProviderError, TryOnEngine, TryOnSpec, TurntableGenerator, TurntableSpec,
                                      Upscaler)
from outfit_core.http import HttpError, request
from outfit_core.registry import register
from outfit_core.types import (Asset, BodySpec, Category, Garment, GarmentAnalysis, TryOnOptions,
                               TurntableOptions)


@register("remote_worker")
class RemoteWorker(Provider, GarmentAnalyzer, GarmentSegmenter, TryOnEngine, Upscaler, TurntableGenerator,
                   ModelImageGenerator):
    def __init__(self, name, config, store):
        super().__init__(name, config, store)
        wanted = config.get("capabilities") or [config.get("capability")]
        unknown = set(wanted) - set(type(self).capabilities)
        if not wanted or None in wanted or unknown:
            raise ValueError(f"providers.{name}: remote_worker 需要 capabilities 列表，未知能力：{unknown or '未填写'}")
        self.capabilities = tuple(wanted)
        self.spec = TryOnSpec(**config.get("spec", {}))
        self.turntable_spec = TurntableSpec(**config.get("turntable_spec", {}))
        self._health_at = 0.0
        self._health = (False, "尚未检查")

    @property
    def url(self):
        return self.config["url"].rstrip("/")

    def available(self):
        if time.time() - self._health_at > self.config.get("health_ttl", 15):
            try:
                r = request("GET", f"{self.url}/v1/health", timeout=5)
                missing = [c for c in self.capabilities if c not in r.get("capabilities", {})]
                self._health = (False, f"worker 未加载能力 {missing}") if missing else (True, "ok")
            except Exception as e:
                self._health = (False, f"worker 无法连接：{e}")
            self._health_at = time.time()
        return self._health

    # ---------- 数据转换 ----------
    def _ref(self, asset: Asset) -> dict:
        if asset.url and not asset.path and self.config.get("send_urls", False):
            return {"url": asset.url}
        return {"data_uri": self.store.to_data_uri(asset)}

    def _asset(self, ref: dict | None) -> Asset | None:
        if not ref:
            return None
        if ref.get("data_uri"):
            return self.store.put_data_uri(ref["data_uri"])
        if ref.get("url"):
            return self.store.save_remote(ref["url"])
        raise ProviderError(f"{self.name}: worker 返回了无法识别的资源 {list(ref)}")

    def _post(self, path: str, body: dict) -> dict:
        try:
            return request("POST", f"{self.url}/v1/{path}", self.config.get("headers"), body,
                           timeout=self.config.get("timeout", 1800))
        except HttpError as e:
            raise ProviderError(f"{self.name}: {e}") from None

    # ---------- 能力实现 ----------
    def analyze(self, image: Asset) -> GarmentAnalysis:
        return GarmentAnalysis.model_validate(self._post("analyze", {"image": self._ref(image)})["analysis"])

    def segment(self, image: Asset, category: Category) -> Asset | None:
        return self._asset(self._post("segment", {"image": self._ref(image), "category": category.value}).get("image"))

    def tryon(self, person: Asset, garments: list[Garment], options: TryOnOptions) -> Asset:
        body = {"person": self._ref(person), "options": options.model_dump(),
                "garments": [{"id": g.id, "category": g.category.value, "image": self._ref(g.tryon_image)}
                             for g in garments]}
        return self._asset(self._post("tryon", body)["image"])

    def upscale(self, image: Asset, scale: int = 2) -> Asset:
        return self._asset(self._post("upscale", {"image": self._ref(image), "scale": scale})["image"])

    def generate(self, image: Asset, options: TurntableOptions):
        r = self._post("turntable", {"image": self._ref(image), "options": options.model_dump()})
        return self._asset(r.get("video")), [self._asset(f) for f in r.get("frames", [])]

    def generate_model(self, body: BodySpec, prompt: str, seed: int | None = None) -> Asset:
        r = self._post("generate_model", {"body": body.model_dump(), "prompt": prompt, "seed": seed})
        return self._asset(r["image"])
