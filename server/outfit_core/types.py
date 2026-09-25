"""统一数据类型。所有适配器之间只传递这些类型，不传递各家接口的原始格式。"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Category(str, Enum):
    top = "top"          # 上衣
    outer = "outer"      # 外套
    bottom = "bottom"    # 裤子
    skirt = "skirt"      # 半身裙
    dress = "dress"      # 连衣裙、连体衣
    shoes = "shoes"
    bag = "bag"
    other = "other"


class Slot(str, Enum):
    """服装在身体上的位置。试衣引擎按位置而不是按品类声明支持范围。"""
    upper = "upper"
    lower = "lower"
    full = "full"


SLOT_OF = {
    Category.top: Slot.upper, Category.outer: Slot.upper,
    Category.bottom: Slot.lower, Category.skirt: Slot.lower,
    Category.dress: Slot.full,
}
TRYON_CATEGORIES = set(SLOT_OF)


class Shot(str, Enum):
    flat_lay = "flat_lay"
    worn_by_model = "worn_by_model"
    mannequin = "mannequin"
    detail = "detail"
    poster = "poster"
    other = "other"


class Asset(BaseModel):
    """一张图片或一段视频。至少有 path 或 url 之一；sha256 在写入本地存储后填充。"""
    path: str | None = None
    url: str | None = None
    sha256: str | None = None
    mime: str | None = None

    @property
    def key(self) -> str:
        return self.sha256 or self.url or self.path or ""


class Product(BaseModel):
    source_text: str
    url: str | None = None
    platform: str | None = None
    title: str | None = None
    price: str | None = None
    images: list[Asset] = Field(default_factory=list)
    affiliate_url: str | None = None
    resolver: str | None = None


class GarmentAnalysis(BaseModel):
    category: Category = Category.other
    layer: Literal["inner", "outer", "none"] = "none"
    shot: Shot = Shot.other
    tryon_ready: bool = False
    color: str | None = None
    note: str | None = None


class Garment(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    image: Asset
    category: Category
    analysis: GarmentAnalysis | None = None
    cutout: Asset | None = None
    product: Product | None = None

    @property
    def tryon_image(self) -> Asset:
        return self.cutout or self.image

    @property
    def slot(self) -> Slot | None:
        return SLOT_OF.get(self.category)


class TryOnOptions(BaseModel):
    tuck: Literal["auto", "in", "out"] = "auto"   # 上衣塞进下装 / 放在外面
    upscale: bool = False
    seed: int | None = None
    extra: dict = Field(default_factory=dict)     # 透传给具体引擎的参数


class CallMetrics(BaseModel):
    capability: str
    provider: str
    seconds: float
    cost: float | None = None
    ok: bool = True
    note: str | None = None
    at: float = Field(default_factory=time.time)


class TryOnStepResult(BaseModel):
    garments: list[str]            # garment id
    image: Asset
    metrics: CallMetrics


class TryOnResult(BaseModel):
    provider: str
    image: Asset
    steps: list[TryOnStepResult] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)   # 引擎不支持而跳过的 garment id
    metrics: list[CallMetrics] = Field(default_factory=list)
    cached: bool = False

    @property
    def total_seconds(self) -> float:
        return round(sum(m.seconds for m in self.metrics), 1)

    @property
    def total_cost(self) -> float | None:
        costs = [m.cost for m in self.metrics]
        return None if any(c is None for c in costs) else round(sum(costs), 4)


class TurntableOptions(BaseModel):
    duration: int = 5
    resolution: str = "720P"
    loop: bool = True              # 首帧同时作为尾帧（引擎支持时）
    prompt: str | None = None      # 为空时用引擎默认提示词
    extra: dict = Field(default_factory=dict)


class TurntableResult(BaseModel):
    provider: str
    video: Asset | None = None
    frames: list[Asset] = Field(default_factory=list)
    metrics: list[CallMetrics] = Field(default_factory=list)
    cached: bool = False


class BodySpec(BaseModel):
    """预设模特的体型参数。"""
    gender: Literal["female", "male"]
    height: Literal["short", "medium", "tall"]
    build: Literal["slim", "regular", "plus"]
    skin: Literal["light", "medium", "dark"]

    @property
    def preset_id(self) -> str:
        return f"{self.gender}-{self.height}-{self.build}-{self.skin}"
