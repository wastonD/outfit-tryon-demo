"""REST 接口的请求/响应模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Category = Literal["top", "outer", "bottom", "skirt", "dress", "shoes", "bag", "other"]
TRYON_CATEGORIES = {"top", "outer", "bottom", "skirt", "dress"}


class ErrorBody(BaseModel):
    code: str
    message: str


class FileRef(BaseModel):
    url: str
    mime: str | None = None


class Source(BaseModel):
    url: str | None = None
    title: str | None = None
    platform: str | None = None
    price: str | None = None
    image_url: str | None = None


class Analysis(BaseModel):
    category: Category
    layer: Literal["inner", "outer", "none"] = "none"
    shot: Literal["flat_lay", "worn_by_model", "mannequin", "detail", "poster", "other"] = "other"
    tryon_ready: bool = False
    color: str | None = None
    note: str | None = None


class Garment(BaseModel):
    id: str
    status: Literal["pending", "processing", "ready", "failed"]
    error: ErrorBody | None = None
    category: Category | None = None
    category_source: Literal["user", "ai"] | None = None
    analysis: Analysis | None = None
    image: FileRef
    cutout: FileRef | None = None
    source: Source
    job_id: str | None = None
    created_at: str


class PresetName(BaseModel):
    zh: str
    en: str


class PresetBody(BaseModel):
    gender: Literal["female", "male"]
    height: Literal["short", "medium", "tall"]
    build: Literal["slim", "regular", "plus"]
    skin: Literal["light", "medium", "dark"]


class Preset(BaseModel):
    id: str
    name: PresetName
    body: PresetBody
    image: FileRef
    internal_only: bool = False


class JobProgress(BaseModel):
    done: int
    total: int
    note: str


class Job(BaseModel):
    id: str
    kind: Literal["prepare_garment", "tryon", "turntable"]
    target_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    progress: JobProgress
    queue_position: int | None = None
    error: ErrorBody | None = None
    created_at: str
    updated_at: str


class OutfitOptions(BaseModel):
    tuck: Literal["auto", "in", "out"] = "auto"
    upscale: bool = False


class OutfitStepResult(BaseModel):
    garment_ids: list[str]
    image: FileRef
    seconds: float


class OutfitResult(BaseModel):
    image: FileRef
    provider: str
    total_seconds: float
    total_cost: float | None = None
    skipped_garment_ids: list[str] = Field(default_factory=list)
    cached: bool = False
    steps: list[OutfitStepResult] = Field(default_factory=list)


class TurntableState(BaseModel):
    status: Literal["none", "queued", "running", "ready", "failed"] = "none"
    job_id: str | None = None
    video: FileRef | None = None
    provider: str | None = None
    error: ErrorBody | None = None


class Outfit(BaseModel):
    id: str
    preset_id: str
    garment_ids: list[str]
    options: OutfitOptions
    status: Literal["queued", "running", "ready", "failed"]
    error: ErrorBody | None = None
    job_id: str
    result: OutfitResult | None = None
    turntable: TurntableState
    created_at: str


class ProviderStatus(BaseModel):
    type: str
    capabilities: list[str]
    available: bool
    reason: str
    commercial_ok: bool
    license: str | None = None
    cost_per_call: float | None = None


class Features(BaseModel):
    analyzer: bool
    tryon: bool
    upscale: bool
    turntable: bool


class Status(BaseModel):
    providers: dict[str, ProviderStatus]
    routes: dict[str, list[str]]
    warnings: list[str]
    features: Features


# ---------- 请求体 ----------

class ImportLinkRequest(BaseModel):
    text: str


class PatchGarmentRequest(BaseModel):
    category: Category


class ReprocessGarmentRequest(BaseModel):
    force_segment: bool = False


class ImportImage(BaseModel):
    url: str | None = None
    data_uri: str | None = None
    category: Category | None = None


class ImportImagesJSONRequest(BaseModel):
    images: list[ImportImage] = Field(default_factory=list)
    source: Source | None = None


class CreateOutfitRequest(BaseModel):
    preset_id: str
    garment_ids: list[str]
    options: OutfitOptions = Field(default_factory=OutfitOptions)


class TurntableRequest(BaseModel):
    duration: int = 5


class FeedbackRequest(BaseModel):
    target_type: Literal["outfit", "garment", "general"]
    target_id: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    text: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _normalize_and_require_one(self):
        if self.text is not None:
            self.text = self.text.strip() or None
        if self.rating is None and self.text is None:
            raise ValueError("rating 和 text 至少提供一个")
        return self
