from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_presets

router = APIRouter()


@router.get("/presets")
def list_presets(presets=Depends(get_presets)):
    return {"items": [p.to_response() for p in presets.values()]}
