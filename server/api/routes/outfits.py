"""搭配：创建试衣任务、360° 任务，以及查询/删除。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from outfit_core.registry import AllProvidersFailed
from outfit_core.types import Asset, TryOnOptions, TurntableOptions

from ..convert import core_garment_from_row, outfit_response, route_available
from ..deps import CurrentUser, get_current_user, get_db, get_jobs, get_presets, get_quota, get_runtime
from ..errors import ApiError
from ..schemas import CreateOutfitRequest, TurntableRequest

router = APIRouter()

TRYON_CATEGORIES = {"top", "outer", "bottom", "skirt", "dress"}


@router.post("/outfits", status_code=202)
def create_outfit(body: CreateOutfitRequest, runtime=Depends(get_runtime), db=Depends(get_db),
                   jobs=Depends(get_jobs), presets=Depends(get_presets), quota=Depends(get_quota),
                   current_user: CurrentUser = Depends(get_current_user)):
    if presets.get(body.preset_id) is None:
        raise ApiError(404, "preset_not_found", "预设模特不存在")
    if not (1 <= len(body.garment_ids) <= 4):
        raise ApiError(400, "bad_request", "garment_ids 数量必须是 1～4 个")

    rows = []
    for gid in body.garment_ids:
        row = db.get_garment_for_user(gid, current_user.user_id)
        if not row:
            raise ApiError(404, "garment_not_found", f"衣物 {gid} 不存在")
        rows.append(row)
    if any(row["status"] != "ready" for row in rows):
        raise ApiError(422, "garment_not_ready", "有衣物尚未处理完成")
    if not any(row["category"] in TRYON_CATEGORIES for row in rows):
        raise ApiError(422, "nothing_to_try_on", "没有可以试穿的服装类型")
    if not route_available(runtime, "tryon"):
        raise ApiError(409, "tryon_unavailable", "试衣功能暂不可用")
    quota.check_and_record(current_user, "outfit")

    outfit = db.create_outfit(preset_id=body.preset_id, garment_ids=body.garment_ids,
                               options=body.options.model_dump(), job_id="", user_id=current_user.user_id)
    job_id = jobs.submit("tryon", outfit["id"], current_user.user_id)
    db.update_outfit(outfit["id"], current_user.user_id, job_id=job_id)
    return outfit_response(db.get_outfit(outfit["id"]))


@router.get("/outfits")
def list_outfits(db=Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    return {"items": [outfit_response(o) for o in db.list_outfits(current_user.user_id)]}


@router.get("/outfits/{outfit_id}")
def get_outfit(outfit_id: str, db=Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    row = db.get_outfit_for_user(outfit_id, current_user.user_id)
    if not row:
        raise ApiError(404, "not_found", "搭配不存在")
    return outfit_response(row)


@router.delete("/outfits/{outfit_id}", status_code=204)
def delete_outfit(outfit_id: str, db=Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    if not db.delete_outfit(outfit_id, current_user.user_id):
        raise ApiError(404, "not_found", "搭配不存在")
    return Response(status_code=204)


@router.post("/outfits/{outfit_id}/turntable", status_code=202)
def create_turntable(outfit_id: str, body: TurntableRequest = TurntableRequest(),
                      runtime=Depends(get_runtime), db=Depends(get_db), jobs=Depends(get_jobs),
                      quota=Depends(get_quota), current_user: CurrentUser = Depends(get_current_user)):
    row = db.get_outfit_for_user(outfit_id, current_user.user_id)
    if not row:
        raise ApiError(404, "not_found", "搭配不存在")
    if row["status"] != "ready":
        raise ApiError(409, "outfit_not_ready", "搭配尚未生成")
    if not route_available(runtime, "turntable"):
        raise ApiError(409, "turntable_unavailable", "360° 功能暂不可用")
    quota.check_and_record(current_user, "turntable")
    db.update_outfit(outfit_id, current_user.user_id, turntable_status="queued", turntable_job_id="",
                      turntable_error_code=None, turntable_error_message=None, turntable_duration=body.duration)
    job_id = jobs.submit("turntable", outfit_id, current_user.user_id)
    db.update_outfit(outfit_id, current_user.user_id, turntable_job_id=job_id)
    return outfit_response(db.get_outfit(outfit_id))


def build_tryon_fn(runtime, db, presets):
    """jobs.register("tryon", ...) 使用：执行叠穿试衣，把结果写回 outfit 行。"""
    def builder(outfit_id: str):
        def fn(report):
            row = db.get_outfit(outfit_id)
            preset = presets[row["preset_id"]]
            core_garments = [core_garment_from_row(db.get_garment(gid)) for gid in row["garment_ids"]]
            options = TryOnOptions(**row["options"])
            db.update_outfit(outfit_id, status="running")
            try:
                result = runtime.pipeline.tryon(preset.image_asset, core_garments, options, on_progress=report)
            except AllProvidersFailed as e:
                message = f"试衣失败：{e}"
                db.update_outfit(outfit_id, status="failed", error_code="tryon_failed", error_message=message)
                raise ApiError(500, "tryon_failed", message) from None
            db.update_outfit(outfit_id, status="ready", error_code=None, error_message=None,
                              result=result.model_dump())
        return fn
    return builder


def build_turntable_fn(runtime, db):
    """jobs.register("turntable", ...) 使用：对试衣结果生成 360° 视频。"""
    def builder(outfit_id: str):
        def fn(report):
            row = db.get_outfit(outfit_id)
            image_asset = Asset(**row["result"]["image"])
            options = TurntableOptions(duration=row.get("turntable_duration") or 5)
            db.update_outfit(outfit_id, turntable_status="running")
            try:
                result = runtime.pipeline.turntable(image_asset, options)
            except AllProvidersFailed as e:
                message = f"360° 生成失败：{e}"
                db.update_outfit(outfit_id, turntable_status="failed", turntable_error_code="turntable_failed",
                                  turntable_error_message=message)
                raise ApiError(500, "turntable_failed", message) from None
            db.update_outfit(
                outfit_id, turntable_status="ready", turntable_error_code=None, turntable_error_message=None,
                turntable_video=result.video.model_dump() if result.video else None,
                turntable_provider=result.provider)
        return fn
    return builder
