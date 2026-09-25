from __future__ import annotations

from fastapi import APIRouter, Depends

from ..convert import route_available
from ..deps import CurrentUser, get_current_user, get_db, get_quota, get_runtime
from ..errors import ApiError
from ..schemas import FeedbackRequest

router = APIRouter()

FEATURE_ROUTES = {"analyzer": "analyzer", "tryon": "tryon", "upscale": "upscaler", "turntable": "turntable"}


@router.get("/me")
def get_me(current_user: CurrentUser = Depends(get_current_user), quota=Depends(get_quota)):
    limit = quota.limit_for(current_user)
    used = quota.used_today(current_user.user_id)
    return {"user_id": current_user.user_id, "name": current_user.name, "mode": current_user.mode,
           "quota": {"daily_outfit_limit": limit, "used_today": used}}


@router.post("/feedback", status_code=201)
def create_feedback(body: FeedbackRequest, db=Depends(get_db),
                    current_user: CurrentUser = Depends(get_current_user)):
    if body.target_type != "general":
        if not body.target_id:
            raise ApiError(400, "bad_request", "target_id 不能为空")
        found = (db.get_outfit_for_user(body.target_id, current_user.user_id)
                if body.target_type == "outfit" else
                db.get_garment_for_user(body.target_id, current_user.user_id))
        if not found:
            raise ApiError(404, "not_found", "反馈指向的资源不存在")
    row = db.create_feedback(user_id=current_user.user_id, target_type=body.target_type,
                             target_id=body.target_id, rating=body.rating, text=body.text)
    return {"id": row["id"]}


@router.get("/status")
def get_status(runtime=Depends(get_runtime)):
    s = runtime.registry.status()
    providers = {
        name: {
            "type": p["type"], "capabilities": p["capabilities"], "available": p["available"], "reason": p["reason"],
            "commercial_ok": p["commercial_ok"], "license": p["license"], "cost_per_call": p["cost_per_call"],
        }
        for name, p in s["providers"].items()
    }
    features = {feature: route_available(runtime, route) for feature, route in FEATURE_ROUTES.items()}
    return {"providers": providers, "routes": s["routes"], "warnings": s["warnings"], "features": features}
