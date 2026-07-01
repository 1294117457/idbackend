"""统一响应格式 - 兼容前端"""
from typing import Any, Optional
from fastapi.responses import JSONResponse


def success_response(
    data: Any = None,
    msg: str = "操作成功",
    code: int = 200,
) -> JSONResponse:
    """成功响应 - 前端兼容格式"""
    return JSONResponse({
        "code": code,
        "msg": msg,
        "data": data,
    })


def error_response(
    msg: str = "操作失败",
    code: int = 500,
    data: Any = None,
) -> JSONResponse:
    """错误响应 - 前端兼容格式"""
    return JSONResponse({
        "code": code,
        "msg": msg,
        "data": data,
    })


# 便捷方法
ok = success_response
fail = error_response
