"""HTTP 请求/响应模型，对应 server/providers/remote_worker.py 里约定的协议。

worker 和 server 是两个独立的 Python 环境（3.12 / 3.14），不共享代码，只通过这份协议通信。
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class Ref(BaseModel):
    """一张图或一段视频：data_uri 和 url 二选一。"""
    data_uri: str | None = None
    url: str | None = None

    @model_validator(mode="after")
    def _one_of(self):
        if not self.data_uri and not self.url:
            raise ValueError("Ref 需要 data_uri 或 url 之一")
        return self


class GarmentRef(BaseModel):
    id: str
    category: str
    image: Ref


class AnalyzeRequest(BaseModel):
    image: Ref


class SegmentRequest(BaseModel):
    image: Ref
    category: str


class TryOnRequest(BaseModel):
    person: Ref
    garments: list[GarmentRef]
    options: dict = Field(default_factory=dict)


class UpscaleRequest(BaseModel):
    image: Ref
    scale: int = 2


class TurntableRequest(BaseModel):
    image: Ref
    options: dict = Field(default_factory=dict)


class GenerateModelRequest(BaseModel):
    body: dict
    prompt: str
    seed: int | None = None
