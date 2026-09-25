"""outfit_core 内部类型 <-> 接口 JSON 之间的转换，以及数据库行 -> 响应 dict 的组装。"""
from __future__ import annotations

from outfit_core.types import Asset, Category, Garment as CoreGarment


def file_ref(asset: dict | None) -> dict | None:
    if not asset:
        return None
    return {"url": f"/files/{asset['sha256']}", "mime": asset.get("mime")}


def error_body(code: str | None, message: str | None) -> dict | None:
    return {"code": code, "message": message} if code else None


def route_available(runtime, route: str) -> bool:
    names = runtime.registry.routes.get(route, [])
    return any(runtime.registry.providers[n].available()[0] for n in names if n in runtime.registry.providers)


def core_garment_from_row(row: dict) -> CoreGarment:
    image = Asset(**row["image"])
    cutout = Asset(**row["cutout"]) if row["cutout"] else None
    return CoreGarment(id=row["id"], image=image, category=Category(row["category"]), cutout=cutout)


def garment_response(row: dict) -> dict:
    return {
        "id": row["id"],
        "status": row["status"],
        "error": error_body(row["error_code"], row["error_message"]),
        "category": row["category"],
        "category_source": row["category_source"],
        "analysis": row["analysis"],
        "image": file_ref(row["image"]),
        "cutout": file_ref(row["cutout"]),
        "source": row["source"],
        "job_id": row["job_id"],
        "created_at": row["created_at"],
    }


def outfit_response(row: dict) -> dict:
    result = None
    r = row["result"]
    if r:
        costs = [m.get("cost") for m in r["metrics"]]
        total_cost = None if any(c is None for c in costs) else round(sum(costs), 4)
        result = {
            "image": file_ref(r["image"]),
            "provider": r["provider"],
            "total_seconds": round(sum(m["seconds"] for m in r["metrics"]), 1),
            "total_cost": total_cost,
            "skipped_garment_ids": r["skipped"],
            "cached": r["cached"],
            "steps": [{"garment_ids": s["garments"], "image": file_ref(s["image"]), "seconds": s["metrics"]["seconds"]}
                      for s in r["steps"]],
        }
    return {
        "id": row["id"],
        "preset_id": row["preset_id"],
        "garment_ids": row["garment_ids"],
        "options": row["options"],
        "status": row["status"],
        "error": error_body(row["error_code"], row["error_message"]),
        "job_id": row["job_id"],
        "result": result,
        "turntable": {
            "status": row["turntable_status"],
            "job_id": row["turntable_job_id"],
            "video": file_ref(row["turntable_video"]),
            "provider": row["turntable_provider"],
            "error": error_body(row["turntable_error_code"], row["turntable_error_message"]),
        },
        "created_at": row["created_at"],
    }


def job_response(row: dict, queue_position: int | None = None) -> dict:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "target_id": row["target_id"],
        "status": row["status"],
        "progress": {"done": row["progress_done"], "total": row["progress_total"], "note": row["progress_note"]},
        "queue_position": queue_position,
        "error": error_body(row["error_code"], row["error_message"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
