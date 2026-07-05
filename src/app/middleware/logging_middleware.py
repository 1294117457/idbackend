"""请求日志中间件

职责：
1. 记录每个 HTTP 请求的方法 / 路径 / 状态码 / 耗时
2. 超过 500ms 或 4xx/5xx → SLOW 输出到 stderr
3. 读取 user_id（AuthMiddleware 写入的 context），记录到日志

为什么不放在 main.py 装饰器？
- main.py 应该只关心"应用入口"，不关心"业务日志格式"
- 多个横切关注点应该统一管理（middleware 目录下）
- 装饰器版本无法获取 user_id 等 context
"""
import sys
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from src.app.context import get_user_id


class LoggingMiddleware(BaseHTTPMiddleware):
    """请求耗时 + 状态码日志中间件"""

    SLOW_THRESHOLD_MS = 500

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        status = response.status_code
        method = request.method
        path = request.url.path
        user_id = get_user_id() or "-"

        line = f"{elapsed_ms:7.0f}ms | {status} | {method} {path} | user={user_id}\n"

        if elapsed_ms > self.SLOW_THRESHOLD_MS or status >= 400:
            sys.stderr.write("SLOW " + line)
            sys.stderr.flush()
        else:
            sys.stdout.write(line)
            sys.stdout.flush()

        return response


__all__ = ["LoggingMiddleware"]