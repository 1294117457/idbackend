"""统一 HTTP 响应工具

设计原则：
- 双 token 场景下 HTTP status_code 与 body.code 解耦
  （如 HTTP 401 + body.code 10001 是 RFC 9110 标准允许的细分场景）
- 业务层 4xx/5xx（不细分场景）保持 HTTP status_code = body.code
- 认证 / 鉴权场景的细分 body.code（10001/10002/10003）在对应工厂里定义

调用约定：
  - 路由层直接调用对应语义函数
  - 中间件使用 unauthorized_resp / forbidden_resp / ...
  - 全局异常由 main.py exception_handler 兜底，路由无需 try/except
"""
from typing import Any
from fastapi.responses import JSONResponse


def _resp(status_code: int, code: int, msg: str, data: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "msg": msg, "data": data},
    )


# ===== 2xx 成功 =====

def query_resp(data: Any = None, msg: str = "") -> JSONResponse:
    """GET 查询专用：HTTP 200，body.code=200，msg 默认空

    与 success_resp 的区别：msg 默认空字符串，前端按"msg 为空不弹 toast"自动静默。
    GET 路由（列表、详情、搜索）一律使用本工厂，避免列表刷新/分页/筛选时反复弹"操作成功"。
    如个别 GET 业务确实需要给用户反馈（如"数据已刷新到最新版本"），可显式传 msg。
    """
    return _resp(200, 200, msg, data)


def success_resp(data: Any = None, msg: str = "操作成功") -> JSONResponse:
    """200 写入成功（POST/PUT/DELETE 与部分 GET 用）"""
    return _resp(200, 200, msg, data)


def created_resp(data: Any = None, msg: str = "创建成功") -> JSONResponse:
    """201 资源创建成功；body code 保持 200 供前端统一判断"""
    return _resp(200, 200, msg, data)


# ===== 4xx 客户端错误 =====

def bad_request_resp(msg: str = "请求参数错误", data: Any = None) -> JSONResponse:
    return _resp(400, 400, msg, data)


def unauthorized_resp(msg: str = "请先登录") -> JSONResponse:
    return _resp(401, 401, msg)


def access_token_expired_resp() -> JSONResponse:
    return _resp(401, 10001, "access_token 已过期")


def refresh_token_expired_resp() -> JSONResponse:
    return _resp(401, 10002, "refresh_token 已过期，请重新登录")


def invalid_token_resp(msg: str = "Token 无效") -> JSONResponse:
    return _resp(401, 10003, msg)


def account_disabled_resp() -> JSONResponse:
    return _resp(401, 10003, "账号已被禁用，请联系管理员")


def forbidden_resp(msg: str = "权限不足") -> JSONResponse:
    return _resp(403, 403, msg)


def not_found_resp(msg: str = "资源不存在") -> JSONResponse:
    return _resp(404, 404, msg)


def too_many_requests_resp(msg: str = "请求过于频繁，请稍后再试") -> JSONResponse:
    return _resp(429, 429, msg)


def conflict_resp(msg: str = "资源冲突") -> JSONResponse:
    return _resp(409, 409, msg)


# ===== 5xx 服务端错误 =====

def server_error_resp(msg: str = "服务器内部错误") -> JSONResponse:
    return _resp(500, 500, msg)