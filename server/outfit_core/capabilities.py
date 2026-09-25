"""七种能力接口。一个适配器类可以实现其中一种或多种。

新增模型的步骤：
  1. 在 providers/ 下写一个类，继承 Provider 和对应的能力基类，实现方法
  2. 用 @register("类型名") 注册
  3. 在 config/providers.yaml 的 providers 里加一个实例，并放进 routes
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from .types import (Asset, BodySpec, Category, Garment, GarmentAnalysis, Product, Slot,
                    TryOnOptions, TurntableOptions)

CAPABILITIES = ("resolver", "analyzer", "segmenter", "tryon", "upscaler", "turntable", "model_generator")


class ProviderError(RuntimeError):
    """适配器调用失败。路由收到后会尝试下一个实现。"""


class ProviderInfo(BaseModel):
    commercial_ok: bool = True        # 许可证或服务协议是否允许商用
    license: str | None = None
    cost_per_call: float | None = 0.0  # 元/次；None 表示未知或按资源包计费
    uses_gpu: bool = False
    vram_gb: float | None = None


class Provider(ABC):
    """所有适配器的基类。config 来自 providers.yaml 中该实例的配置。"""
    capabilities: tuple[str, ...] = ()
    default_info = ProviderInfo()

    def __init__(self, name: str, config: dict, store):
        self.name = name
        self.config = config
        self.store = store   # AssetStore，用于落盘、下载和格式转换
        self.info = self.default_info.model_copy(update=config.get("info", {}))

    def available(self) -> tuple[bool, str]:
        """是否可用（例如密钥是否配置、本地服务是否启动）。路由会跳过不可用的实现。"""
        return True, "ok"

    def close(self):
        pass


class LinkResolver(ABC):
    @abstractmethod
    def can_handle(self, text: str) -> bool: ...

    @abstractmethod
    def resolve(self, text: str) -> Product: ...


class GarmentAnalyzer(ABC):
    @abstractmethod
    def analyze(self, image: Asset) -> GarmentAnalysis: ...


class GarmentSegmenter(ABC):
    @abstractmethod
    def segment(self, image: Asset, category: Category) -> Asset | None: ...


class TryOnSpec(BaseModel):
    """试衣引擎的能力描述，流程据此决定一次传几件、怎么拆步骤。"""
    slots: set[Slot] = Field(default_factory=lambda: {Slot.upper, Slot.lower, Slot.full})
    max_garments_per_call: int = 1          # 一次调用最多几件（每个位置最多一件）
    supports_tuck: bool = False
    supports_layering: bool = True          # 能否在已穿衣服的结果上再叠一件外套


class TryOnEngine(ABC):
    spec = TryOnSpec()

    @abstractmethod
    def tryon(self, person: Asset, garments: list[Garment], options: TryOnOptions) -> Asset:
        """garments 数量不超过 spec.max_garments_per_call，且位置互不重复。"""


class Upscaler(ABC):
    @abstractmethod
    def upscale(self, image: Asset, scale: int = 2) -> Asset: ...


class TurntableSpec(BaseModel):
    supports_last_frame: bool = False
    output: str = "video"      # video 或 frames


class TurntableGenerator(ABC):
    turntable_spec = TurntableSpec()

    @abstractmethod
    def generate(self, image: Asset, options: TurntableOptions) -> tuple[Asset | None, list[Asset]]:
        """返回 (视频, 多角度图列表)，至少其一非空。"""


class ModelImageGenerator(ABC):
    @abstractmethod
    def generate_model(self, body: BodySpec, prompt: str, seed: int | None = None) -> Asset: ...


CAPABILITY_BASES = {
    "resolver": LinkResolver, "analyzer": GarmentAnalyzer, "segmenter": GarmentSegmenter,
    "tryon": TryOnEngine, "upscaler": Upscaler, "turntable": TurntableGenerator,
    "model_generator": ModelImageGenerator,
}
