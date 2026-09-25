"""FastAPI 应用工厂：组装 Runtime、数据库、任务队列，挂载路由和错误处理。"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from outfit_core.bootstrap import Runtime, SERVER_ROOT, build, setup_console

from .db import Database
from .deps import get_current_user
from .errors import ApiError, install_error_handlers
from .jobs import JobRunner
from .presets_data import load_presets
from .quota import QuotaChecker
from .routes import files, garments, imports, jobs as jobs_routes, outfits, presets, status

log = logging.getLogger("outfit.api")

CORS_ORIGIN_REGEX = r"^(http://localhost:5173|http://127\.0\.0\.1:5173|chrome-extension://.*)$"


def create_app(runtime: Runtime | None = None, db_path: str | Path | None = None,
              sync: bool | None = None) -> FastAPI:
    setup_console()
    runtime = runtime or build()
    if sync is None:
        sync = os.environ.get("OUTFIT_SYNC_JOBS", "").lower() in ("1", "true", "yes")
    default_db = Path(os.environ.get("OUTFIT_DATA", SERVER_ROOT / "data")) / "api.sqlite3"
    db = Database(db_path or default_db)
    db.recover_running_jobs()
    presets_map = load_presets(runtime.store)

    job_runner = JobRunner(db, sync=sync)
    job_runner.register("prepare_garment", imports.build_prepare_garment_fn(runtime, db))
    job_runner.register("tryon", outfits.build_tryon_fn(runtime, db, presets_map))
    job_runner.register("turntable", outfits.build_turntable_fn(runtime, db))

    app = FastAPI(title="穿搭试衣 API")
    app.state.runtime = runtime
    app.state.db = db
    app.state.jobs = job_runner
    app.state.presets = presets_map
    app.state.quota = QuotaChecker(db)

    app.add_middleware(CORSMiddleware, allow_origin_regex=CORS_ORIGIN_REGEX, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    install_error_handlers(app)

    api_routers = (status.router, presets.router, imports.router, garments.router, outfits.router, jobs_routes.router)
    for r in api_routers:
        app.include_router(r, prefix="/api", dependencies=[Depends(get_current_user)])
    app.include_router(files.router)

    for w in runtime.registry.warnings:
        log.warning(w)

    web_dist = (SERVER_ROOT.parent / "web" / "dist").resolve()
    if web_dist.exists():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="web-assets")

        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str):
            # 未匹配的 /api、/files 路径按接口 404 处理，不能回退成网页
            if full_path == "api" or full_path.startswith(("api/", "files/")) or full_path == "files":
                raise ApiError(404, "not_found", "接口不存在")
            candidate = (web_dist / full_path).resolve()
            # 防止 ../ 穿越读取 web/dist 以外的文件（例如 server/.env）
            if candidate.is_relative_to(web_dist) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(web_dist / "index.html")

    return app


app = create_app()
