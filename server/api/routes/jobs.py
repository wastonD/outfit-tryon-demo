from __future__ import annotations

from fastapi import APIRouter, Depends

from ..convert import job_response
from ..deps import CurrentUser, get_current_user, get_db, get_jobs, get_quota
from ..errors import ApiError

router = APIRouter()

# 重试哪些 kind 计入每日额度（v1.4"额度"一节）
RETRY_QUOTA_KIND = {"tryon": "retry_tryon", "turntable": "retry_turntable"}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db=Depends(get_db), jobs=Depends(get_jobs),
           current_user: CurrentUser = Depends(get_current_user)):
    row = db.get_job_for_user(job_id, current_user.user_id)
    if not row:
        raise ApiError(404, "not_found", "任务不存在")
    return job_response(row, jobs.queue_position(job_id))


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str, jobs=Depends(get_jobs), quota=Depends(get_quota),
             current_user: CurrentUser = Depends(get_current_user)):
    def before_dispatch(job: dict):
        kind = RETRY_QUOTA_KIND.get(job["kind"])
        if kind:
            quota.check_and_record(current_user, kind)

    row = jobs.retry(job_id, current_user.user_id, on_before_dispatch=before_dispatch)
    return job_response(row, jobs.queue_position(job_id))
