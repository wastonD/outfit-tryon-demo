from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from ..convert import garment_response
from ..deps import CurrentUser, get_current_user, get_db, get_jobs
from ..errors import ApiError
from ..schemas import PatchGarmentRequest, ReprocessGarmentRequest

router = APIRouter()


@router.get("/garments")
def list_garments(status: str | None = None, category: str | None = None, db=Depends(get_db),
                  current_user: CurrentUser = Depends(get_current_user)):
    items = db.list_garments(current_user.user_id, status=status, category=category)
    return {"items": [garment_response(g) for g in items]}


@router.get("/garments/{garment_id}")
def get_garment(garment_id: str, db=Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    row = db.get_garment_for_user(garment_id, current_user.user_id)
    if not row:
        raise ApiError(404, "not_found", "衣物不存在")
    return garment_response(row)


@router.patch("/garments/{garment_id}")
def patch_garment(garment_id: str, body: PatchGarmentRequest, db=Depends(get_db),
                  current_user: CurrentUser = Depends(get_current_user)):
    row = db.get_garment_for_user(garment_id, current_user.user_id)
    if not row:
        raise ApiError(404, "not_found", "衣物不存在")
    updates = {"category": body.category, "category_source": "user"}
    if row["status"] == "failed" and row["error_code"] == "category_required":
        updates.update(status="ready", error_code=None, error_message=None)
    db.update_garment(garment_id, current_user.user_id, **updates)
    return garment_response(db.get_garment_for_user(garment_id, current_user.user_id))


@router.delete("/garments/{garment_id}", status_code=204)
def delete_garment(garment_id: str, db=Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    if not db.delete_garment(garment_id, current_user.user_id):
        raise ApiError(404, "not_found", "衣物不存在")
    return Response(status_code=204)


@router.post("/garments/{garment_id}/reprocess", status_code=202)
def reprocess_garment(garment_id: str, body: ReprocessGarmentRequest = ReprocessGarmentRequest(),
                      db=Depends(get_db), jobs=Depends(get_jobs),
                      current_user: CurrentUser = Depends(get_current_user)):
    row = db.get_garment_for_user(garment_id, current_user.user_id)
    if not row:
        raise ApiError(404, "not_found", "衣物不存在")
    if row["status"] in ("pending", "processing"):
        raise ApiError(409, "garment_busy", "衣物正在处理中")
    db.update_garment(garment_id, current_user.user_id, status="pending",
                      force_segment=1 if body.force_segment else 0)
    job_id = jobs.submit("prepare_garment", garment_id, current_user.user_id)
    db.update_garment(garment_id, current_user.user_id, job_id=job_id)
    return garment_response(db.get_garment_for_user(garment_id, current_user.user_id))
