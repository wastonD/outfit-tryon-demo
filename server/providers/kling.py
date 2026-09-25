"""可灵 AI 虚拟试穿（一次一件）。需要在可灵开放平台购买资源包。
接口域名和模型名以官方最新文档为准，可在配置中用 base_url、model 覆盖。
"""
import base64
import hashlib
import hmac
import json
import os
import time

from outfit_core.capabilities import Provider, ProviderError, ProviderInfo, TryOnEngine, TryOnSpec
from outfit_core.http import HttpError, poll, request
from outfit_core.registry import register
from outfit_core.types import Asset, Garment, TryOnOptions

PATH = "/v1/images/kolors-virtual-try-on"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_jwt(ak: str, sk: str, now: int | None = None) -> str:
    now = int(now or time.time())
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({"iss": ak, "exp": now + 1800, "nbf": now - 5}).encode())
    sig = hmac.new(sk.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(sig)}"


@register("kling_tryon")
class KlingTryOn(Provider, TryOnEngine):
    spec = TryOnSpec(max_garments_per_call=1, supports_layering=True)
    default_info = ProviderInfo(license="可灵开放平台服务协议", cost_per_call=None)

    @property
    def base(self):
        return self.config.get("base_url", "https://api-beijing.klingai.com").rstrip("/")

    def _keys(self):
        return (os.environ.get(self.config.get("access_key_env", "KLING_ACCESS_KEY")),
                os.environ.get(self.config.get("secret_key_env", "KLING_SECRET_KEY")))

    def available(self):
        return (True, "ok") if all(self._keys()) else (False, "未设置 KLING_ACCESS_KEY / KLING_SECRET_KEY")

    def _auth(self):
        return {"Authorization": f"Bearer {make_jwt(*self._keys())}"}

    def _image(self, asset: Asset) -> str:
        return asset.url if asset.url else self.store.to_base64(asset)

    def tryon(self, person: Asset, garments: list[Garment], options: TryOnOptions) -> Asset:
        body = {"model_name": self.config.get("model", "kolors-virtual-try-on-v1-5"),
                "human_image": self._image(person), "cloth_image": self._image(garments[0].tryon_image)}
        try:
            r = request("POST", self.base + PATH, self._auth(), body)
            if r.get("code") != 0:
                raise ProviderError(f"可灵提交失败：{json.dumps(r, ensure_ascii=False)[:300]}")
            task_id = r["data"]["task_id"]

            def done(res):
                status = res.get("data", {}).get("task_status")
                if status == "failed":
                    raise ProviderError(f"可灵任务失败：{res['data'].get('task_status_msg')}")
                return status == "succeed"

            res = poll(lambda: request("GET", f"{self.base}{PATH}/{task_id}", self._auth()), done, 4, 900, "可灵试穿")
        except HttpError as e:
            raise ProviderError(f"{self.name}: {e}") from None
        return self.store.save_remote(res["data"]["task_result"]["images"][0]["url"])
