from __future__ import annotations

import mimetypes
import re

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from ..deps import get_current_user_file, get_runtime
from ..errors import ApiError

router = APIRouter()

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@router.get("/files/{sha256}")
def get_file(sha256: str, runtime=Depends(get_runtime), _=Depends(get_current_user_file)):
    if not SHA256_RE.match(sha256):
        raise ApiError(404, "not_found", "文件不存在")
    store = runtime.store
    matches = sorted((store.root / sha256[:2]).glob(f"{sha256}.*")) if (store.root / sha256[:2]).exists() else []
    if not matches:
        raise ApiError(404, "not_found", "文件不存在")
    path = matches[0]
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "public, max-age=31536000, immutable"})
