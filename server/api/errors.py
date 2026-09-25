"""统一错误类型和异常处理器：所有非 2xx 响应都输出 {"error": {"code", "message"}}。"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger("outfit.api")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def install_error_handlers(app: FastAPI):
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status, content=_body(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=400, content=_body("bad_request", "请求参数格式错误"))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        log.exception("未处理的异常：%s", exc)
        return JSONResponse(status_code=500, content=_body("internal_error", "服务器内部错误"))
