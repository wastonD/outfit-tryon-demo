"""阿里云百炼（北京地域）：AI 试衣、服装分割、万相图生视频。

文档：
  试衣 https://help.aliyun.com/zh/model-studio/aitryon-plus-api
  分割 https://help.aliyun.com/zh/model-studio/aitryon-parsing-api
  图生视频 https://help.aliyun.com/zh/model-studio/image-to-video-general-api-reference
  临时上传 https://help.aliyun.com/zh/model-studio/get-temporary-file-url
价格（2026-09 查询）：aitryon 0.2 元/张，aitryon-plus 0.5 元/张，aitryon-parsing-v1 0.004 元/张。
"""
import json
import os
from pathlib import Path

from outfit_core.capabilities import (GarmentSegmenter, ModelImageGenerator, Provider, ProviderError, ProviderInfo,
                                      TryOnEngine, TryOnSpec, TurntableGenerator, TurntableSpec)
from outfit_core.http import HttpError, multipart, poll, request
from outfit_core.registry import register
from outfit_core.types import Asset, BodySpec, Category, Garment, Slot, TryOnOptions, TurntableOptions

from ._prompts import TURNTABLE_PROMPT

PRICES = {"aitryon": 0.20, "aitryon-plus": 0.50, "aitryon-parsing-v1": 0.004}


class DashScopeMixin(Provider):
    """共用的鉴权、临时文件上传、异步任务轮询。配置：api_key_env（默认 DASHSCOPE_API_KEY）、base_url。"""

    @property
    def base(self):
        return self.config.get("base_url", "https://dashscope.aliyuncs.com").rstrip("/")

    def _key(self):
        return os.environ.get(self.config.get("api_key_env", "DASHSCOPE_API_KEY"))

    def available(self):
        return (True, "ok") if self._key() else (False, "未设置 DASHSCOPE_API_KEY")

    def _headers(self, async_=False, oss=False):
        h = {"Authorization": f"Bearer {self._key()}"}
        if async_:
            h["X-DashScope-Async"] = "enable"
        if oss:
            h["X-DashScope-OssResourceResolve"] = "enable"
        return h

    def _call(self, method, url, body=None, **headers_kw):
        try:
            return request(method, url, self._headers(**headers_kw), body)
        except HttpError as e:
            raise ProviderError(f"{self.name}: {e}") from None

    def _upload(self, asset: Asset, model: str) -> str:
        local = self.store.ensure_local(asset)
        policy = self._call("GET", f"{self.base}/api/v1/uploads?action=getPolicy&model={model}")["data"]
        key = f"{policy['upload_dir']}/{Path(local.path).name}"
        body, ctype = multipart({
            "OSSAccessKeyId": policy["oss_access_key_id"], "Signature": policy["signature"],
            "policy": policy["policy"], "key": key, "x-oss-object-acl": policy["x_oss_object_acl"],
            "x-oss-forbid-overwrite": policy["x_oss_forbid_overwrite"], "success_action_status": "200",
        }, "file", local.path)
        request("POST", policy["upload_host"], {"Content-Type": ctype}, body, raw=True)
        return f"oss://{key}"

    def _url_for(self, asset: Asset, model: str) -> tuple[str, bool]:
        """返回 (可用地址, 是否需要 OSS 解析头)。有长期有效的公网 URL 直接用，否则上传（免费）。

        百炼生成结果的 URL 只有 24 小时有效，缓存复用时可能已过期，所以有本地文件时改为重新上传。
        """
        if asset.url and asset.url.startswith(("http://", "https://")):
            expiring = "dashscope-result" in asset.url and asset.path
            if not expiring:
                return asset.url, False
        return self._upload(asset, model), True

    def _wait(self, task_id, label, interval=4, timeout=900):
        def done(r):
            status = r.get("output", {}).get("task_status")
            if status in ("FAILED", "CANCELED", "UNKNOWN"):
                raise ProviderError(f"{label} 失败：{json.dumps(r, ensure_ascii=False)[:500]}")
            return status == "SUCCEEDED"
        return poll(lambda: self._call("GET", f"{self.base}/api/v1/tasks/{task_id}"), done, interval, timeout, label)


@register("aliyun_tryon")
class AliyunTryOn(DashScopeMixin, TryOnEngine):
    """一次可同时试上衣和下装；连衣裙作为上衣传入；外套作为第二步叠加。配置：model: aitryon | aitryon-plus"""
    spec = TryOnSpec(max_garments_per_call=2, supports_layering=True)
    default_info = ProviderInfo(license="阿里云百炼服务协议", cost_per_call=0.5)

    def __init__(self, name, config, store):
        config.setdefault("model", "aitryon-plus")
        super().__init__(name, config, store)
        if "cost_per_call" not in config.get("info", {}):
            self.info.cost_per_call = PRICES.get(config["model"])

    def tryon(self, person: Asset, garments: list[Garment], options: TryOnOptions) -> Asset:
        model = self.config["model"]
        inp, use_oss = {}, False
        inp["person_image_url"], o = self._url_for(person, model)
        use_oss |= o
        for g in garments:
            field = "bottom_garment_url" if g.slot == Slot.lower else "top_garment_url"
            inp[field], o = self._url_for(g.tryon_image, model)
            use_oss |= o
        body = {"model": model, "input": inp,
                "parameters": {"resolution": self.config.get("resolution", -1),
                               "restore_face": self.config.get("restore_face", True), **options.extra}}
        task_id = self._call("POST", f"{self.base}/api/v1/services/aigc/image2image/image-synthesis", body,
                             async_=True, oss=use_oss)["output"]["task_id"]
        result = self._wait(task_id, model)
        return self.store.save_remote(result["output"]["image_url"])


@register("aliyun_segmenter")
class AliyunSegmenter(DashScopeMixin, GarmentSegmenter):
    """配置 endpoint 可改成控制台显示的业务空间地址。"""
    default_info = ProviderInfo(license="阿里云百炼服务协议", cost_per_call=PRICES["aitryon-parsing-v1"])

    def segment(self, image: Asset, category: Category) -> Asset | None:
        clothes_type = {Category.bottom: "lower", Category.skirt: "lower", Category.dress: "dress"}.get(category, "upper")
        url, use_oss = self._url_for(image, "aitryon-parsing-v1")
        endpoint = self.config.get("endpoint", f"{self.base}/api/v1/services/vision/image-process/process")
        r = self._call("POST", endpoint, {"model": "aitryon-parsing-v1", "input": {"image_url": url},
                                          "parameters": {"clothes_type": [clothes_type]}}, oss=use_oss)
        crops = r.get("output", {}).get("crop_img_url") or [None]
        return self.store.save_remote(crops[0]) if crops[0] else None


@register("aliyun_wan_turntable")
class AliyunWanTurntable(DashScopeMixin, TurntableGenerator):
    """万相图生视频。配置：model（默认 wan2.7-i2v-2026-04-25）、prompt。价格请以控制台为准。"""
    turntable_spec = TurntableSpec(supports_last_frame=True)
    default_info = ProviderInfo(license="阿里云百炼服务协议", cost_per_call=None)

    def generate(self, image: Asset, options: TurntableOptions):
        src = image.url if image.url else self.store.to_data_uri(image)
        media = [{"type": "first_frame", "url": src}]
        if options.loop:
            media.append({"type": "last_frame", "url": src})
        body = {"model": self.config.get("model", "wan2.7-i2v-2026-04-25"),
                "input": {"prompt": options.prompt or self.config.get("prompt", TURNTABLE_PROMPT), "media": media},
                "parameters": {"resolution": options.resolution, "duration": options.duration,
                               "prompt_extend": False, "watermark": False, **options.extra}}
        task_id = self._call("POST", f"{self.base}/api/v1/services/aigc/video-generation/video-synthesis", body,
                             async_=True)["output"]["task_id"]
        result = self._wait(task_id, "图生视频", interval=10, timeout=1800)
        return self.store.save_remote(result["output"]["video_url"]), []


# 万相文生图（生成预设模特底图，批量脚本见 bench/gen_presets.py）。
# 价格（2026-09 查询 https://help.aliyun.com/en/model-studio/model-pricing 的 Wanx Text-to-Image 表，均为元/张，
# 括号内是新用户免费额度）：wanx2.0-t2i-turbo 0.04（500）、wanx-v1 0.16（500）、wanx2.1-t2i-turbo 0.14（500）、
# wanx2.1-t2i-plus 0.20（500）、wan2.2-t2i-flash 0.14（100）、wan2.2-t2i-plus 0.20（100）、
# wan2.5-t2i-preview 0.20（50）、wan2.6-t2i 0.20（50）。
T2I_PRICES = {"wanx2.0-t2i-turbo": 0.04, "wanx-v1": 0.16, "wanx2.1-t2i-turbo": 0.14, "wanx2.1-t2i-plus": 0.20,
             "wan2.2-t2i-flash": 0.14, "wan2.2-t2i-plus": 0.20, "wan2.5-t2i-preview": 0.20, "wan2.6-t2i": 0.20}
# wan2.6 起用新协议（messages 格式），支持 HTTP 同步调用；wan2.5 及以下仍是旧协议（prompt 字符串），只能异步轮询。
T2I_SYNC_MODELS = {"wan2.6-t2i"}
T2I_DEFAULT_NEGATIVE_PROMPT = ("低分辨率，低画质，肢体畸形，手指畸形，多余的肢体，比例失调，"
                               "配饰，手镯，手链，佛珠，腕带，项链，耳环，戒指，手表，文字，水印，logo，多人，"
                               "连体衣，泳衣，连衣裙，运动鞋，球鞋，暗角，背景渐变，"
                               "僵硬姿势，立正军姿，呆板表情，紧绷，"
                               "卡通，动漫，插画，过度磨皮，侧面，背面，坐姿，模糊")


@register("aliyun_wan_t2i")
class AliyunWanT2I(DashScopeMixin, ModelImageGenerator):
    """万相文生图，用于生成预设模特底图。配置：
      model（默认 wanx2.1-t2i-turbo：单价低、免费额度大，且尺寸范围 [512,1440] 每边可直接覆盖下面的默认竖版比例）
      size（默认 576*864，2:3 竖版，与 FASHN 试衣引擎的输入比例一致，见 worker/app/vendor/fashn_vton/pipeline.py
           里 tryon_model.input_shape=(864,576)；若换成 wan2.5/2.6 等要求总像素约束的型号，两边都不在
           [512,1440] 内时需要在本地居中留白裁切，本类不处理，由调用方负责）
      negative_prompt（默认见 T2I_DEFAULT_NEGATIVE_PROMPT，覆盖 D 报告里提到的幻觉手镯等问题）
      prompt_extend（默认关闭：智能改写可能引入受版权保护的内容触发审核失败，见文生图 API 文档）
    """
    default_info = ProviderInfo(license="阿里云百炼服务协议", cost_per_call=None)

    def __init__(self, name, config, store):
        config.setdefault("model", "wanx2.1-t2i-turbo")
        super().__init__(name, config, store)
        if "cost_per_call" not in config.get("info", {}):
            self.info.cost_per_call = T2I_PRICES.get(config["model"])

    def generate_model(self, body: BodySpec, prompt: str, seed: int | None = None) -> Asset:
        model = self.config["model"]
        params = {"size": self.config.get("size", "576*864"), "n": 1, "watermark": False,
                 "prompt_extend": self.config.get("prompt_extend", False)}
        negative = self.config.get("negative_prompt", T2I_DEFAULT_NEGATIVE_PROMPT)
        if negative:
            params["negative_prompt"] = negative
        if seed is not None:
            params["seed"] = seed

        if model in T2I_SYNC_MODELS:
            req = {"model": model, "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
                  "parameters": params}
            r = self._call("POST", f"{self.base}/api/v1/services/aigc/multimodal-generation/generation", req)
            url = r["output"]["choices"][0]["message"]["content"][0]["image"]
        else:
            req = {"model": model, "input": {"prompt": prompt}, "parameters": params}
            task_id = self._call("POST", f"{self.base}/api/v1/services/aigc/text2image/image-synthesis", req,
                                 async_=True)["output"]["task_id"]
            result = self._wait(task_id, model)
            url = result["output"]["results"][0]["url"]
        return self.store.save_remote(url)
