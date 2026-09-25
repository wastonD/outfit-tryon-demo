"""导入：解析链接（不建衣物）、导入图片（每张图建一件衣物 + 一个 prepare_garment 任务）。"""
from __future__ import annotations

import base64
import io
import re

from fastapi import APIRouter, Depends, Request
from PIL import Image
from pillow_heif import register_heif_opener

from outfit_core.registry import AllProvidersFailed
from outfit_core.types import Asset, Category

from ..convert import garment_response
from ..deps import CurrentUser, get_current_user, get_db, get_jobs, get_runtime
from ..downloads import fetch_image
from ..errors import ApiError
from ..schemas import ImportImagesJSONRequest, ImportLinkRequest

register_heif_opener()  # 让 Pillow 认识 .heic/.heif；avif 由 Pillow 12+ 原生支持，无需额外插件

router = APIRouter()

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGES = 10
URL_RE = re.compile(r"https?://")
DATA_URI_RE = re.compile(r"data:([^;]+);base64,(.*)", re.S)
CONVERT_TO_PNG_FORMATS = {"AVIF", "HEIF"}

EMPTY_SOURCE = {"url": None, "title": None, "platform": None, "price": None, "image_url": None}


@router.post("/import/link")
def import_link(body: ImportLinkRequest, runtime=Depends(get_runtime)):
    if not URL_RE.search(body.text):
        raise ApiError(400, "no_url", "文本里没有找到链接")
    try:
        product = runtime.pipeline.resolve_link(body.text)
    except AllProvidersFailed:
        raise ApiError(422, "resolve_failed", "无法解析该链接，建议使用淘宝联盟接口或浏览器插件导入图片")
    return {"product": {
        "url": product.url, "platform": product.platform, "title": product.title, "price": product.price,
        "images": [a.url or a.path for a in product.images if a.url or a.path][:10],
    }}


def _check_size(data: bytes):
    if len(data) > MAX_IMAGE_BYTES:
        raise ApiError(413, "file_too_large", "图片超过 10MB 限制")


def _normalize_image(data: bytes, mime: str | None) -> tuple[bytes, str | None]:
    """校验图片能否解码；avif/heic 统一转换成 png 后再存储，其他格式原样返回。"""
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as img:
            if img.format not in CONVERT_TO_PNG_FORMATS:
                return data, mime
            if img.mode == "RGBA" or (img.mode == "P" and "transparency" in img.info):
                img = img.convert("RGBA")
            else:
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue(), "image/png"
    except Exception:
        raise ApiError(422, "unsupported_image", "不支持的图片格式") from None


def _decode_data_uri(uri: str) -> tuple[bytes, str | None]:
    match = DATA_URI_RE.match(uri)
    if not match:
        raise ApiError(422, "unsupported_image", "不是合法的 data URI")
    try:
        return base64.b64decode(match.group(2)), match.group(1)
    except Exception:
        raise ApiError(422, "unsupported_image", "不是合法的 data URI") from None


def _create_garment_and_job(runtime, db, jobs, *, image_asset: Asset, category: str | None, source: dict,
                            user_id: str) -> dict:
    garment = db.create_garment(
        status="pending", category=category, category_source="user" if category else None,
        image=image_asset.model_dump(), source=source, user_id=user_id)
    job_id = jobs.submit("prepare_garment", garment["id"], user_id)
    db.update_garment(garment["id"], user_id, job_id=job_id)
    return db.get_garment(garment["id"])


@router.post("/import/images", status_code=202)
async def import_images(request: Request, runtime=Depends(get_runtime), db=Depends(get_db), jobs=Depends(get_jobs),
                        current_user: CurrentUser = Depends(get_current_user)):
    content_type = request.headers.get("content-type", "")
    items: list[dict] = []

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        files = form.getlist("files")
        if not files:
            raise ApiError(400, "no_images", "没有上传图片")
        if len(files) > MAX_IMAGES:
            raise ApiError(422, "unsupported_image", f"最多一次导入 {MAX_IMAGES} 张")
        category = form.get("category") or None
        if category:
            try:
                category = Category(category).value
            except ValueError:
                raise ApiError(400, "bad_request", f"未知的服装类型：{category}") from None
        source = {
            "url": form.get("source_url") or None, "title": form.get("source_title") or None,
            "platform": form.get("source_platform") or None, "price": form.get("source_price") or None,
            "image_url": None,
        }
        for f in files:
            data = await f.read()
            _check_size(data)
            data, mime = _normalize_image(data, f.content_type)
            asset = runtime.store.put_bytes(data, mime)
            items.append(_create_garment_and_job(runtime, db, jobs, image_asset=asset, category=category,
                                                 source=source, user_id=current_user.user_id))
    else:
        payload = await request.json()
        body = ImportImagesJSONRequest.model_validate(payload)
        if not body.images:
            raise ApiError(400, "no_images", "没有图片")
        if len(body.images) > MAX_IMAGES:
            raise ApiError(422, "unsupported_image", f"最多一次导入 {MAX_IMAGES} 张")
        source = body.source.model_dump() if body.source else dict(EMPTY_SOURCE)
        for img in body.images:
            if img.data_uri:
                data, mime = _decode_data_uri(img.data_uri)
            elif img.url:
                try:
                    data, mime = fetch_image(img.url, referer=source.get("url"))
                except Exception:
                    raise ApiError(422, "unsupported_image", "图片下载失败") from None
            else:
                raise ApiError(400, "no_images", "每项必须有 url 或 data_uri")
            _check_size(data)
            data, mime = _normalize_image(data, mime)
            asset = runtime.store.put_bytes(data, mime)
            items.append(_create_garment_and_job(runtime, db, jobs, image_asset=asset, category=img.category,
                                                 source=source, user_id=current_user.user_id))

    return {"items": [garment_response(g) for g in items]}


def build_prepare_garment_fn(runtime, db):
    """jobs.register("prepare_garment", ...) 使用：处理识别 + 抠图，并把结果写回 garment 行。

    同一个 kind 也承担 reprocess：garment.category_source 为 user 时保留用户指定的类型，
    否则每次都用当前识别结果；force_segment 为 true 时（reprocess 专用），不管 shot 是什么都按当前类型抠图。
    """
    def builder(garment_id: str):
        def fn(report):
            db.update_garment(garment_id, status="processing")
            row = db.get_garment(garment_id)
            image_asset = Asset(**row["image"])
            user_category = Category(row["category"]) if row["category_source"] == "user" else None
            force_segment = bool(row["force_segment"])
            try:
                core_garment, _metrics = runtime.pipeline.prepare_garment(
                    image_asset, user_category, force_segment=force_segment)
            except (ValueError, AllProvidersFailed):
                message = "无法识别服装类型，请手动指定"
                db.update_garment(garment_id, status="failed", error_code="category_required", error_message=message)
                raise ApiError(400, "category_required", message) from None
            cutout = core_garment.cutout  # 抠图失败时为 None，衣物仍为 ready
            db.update_garment(
                garment_id, status="ready", error_code=None, error_message=None, force_segment=0,
                category=core_garment.category.value,
                category_source="user" if user_category else "ai",
                analysis=core_garment.analysis.model_dump() if core_garment.analysis else None,
                cutout=cutout.model_dump() if cutout else None)
        return fn
    return builder
