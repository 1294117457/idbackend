"""统一 HTTP 响应工具

设计原则：HTTP status_code 与 body.code 保持一致（RESTful 流派）
  - 路由层直接调用对应语义函数
  - 中间件使用 unauthorized_resp / forbidden_resp
  - 全局异常由 main.py exception_handler 兜底，路由无需 try/except
"""
from typing import Any
from fastapi.responses import JSONResponse


def _resp(code: int, msg: str, data: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=code,
        content={"code": code, "msg": msg, "data": data},
    )


# ===== 2xx 成功 =====

def success_resp(data: Any = None, msg: str = "操作成功") -> JSONResponse:
    """200 查询 / 更新 / 删除成功"""
    return _resp(200, msg, data)


def created_resp(data: Any = None, msg: str = "创建成功") -> JSONResponse:
    """201 资源创建成功；body code 保持 200 供前端统一判断"""
    return _resp(200, msg, data)


# ===== 4xx 客户端错误 =====

def bad_request_resp(msg: str = "请求参数错误", data: Any = None) -> JSONResponse:
    """400 请求参数不合法 / 业务校验失败"""
    return _resp(400, msg, data)


def unauthorized_resp(msg: str = "请先登录") -> JSONResponse:
    """401 未登录 / Token 无效或过期"""
    return _resp(401, msg)


def forbidden_resp(msg: str = "权限不足") -> JSONResponse:
    """403 已登录但无操作权限"""
    return _resp(403, msg)


def not_found_resp(msg: str = "资源不存在") -> JSONResponse:
    """404 目标资源不存在"""
    return _resp(404, msg)


def too_many_requests_resp(msg: str = "请求过于频繁，请稍后再试") -> JSONResponse:
    """429 触发限流"""
    return _resp(429, msg)


def conflict_resp(msg: str = "资源冲突") -> JSONResponse:
    """409 业务状态冲突（如重复投票、状态不允许）"""
    return _resp(409, msg)


# ===== 5xx 服务端错误 =====

def server_error_resp(msg: str = "服务器内部错误") -> JSONResponse:
    """500 未预期的服务端异常"""
    return _resp(500, msg)
