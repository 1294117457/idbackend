"""CORS 中间件配置

从 Settings 读取配置，避免在 register_middlewares 里硬编码：
- 开发环境：ALLOWED_ORIGINS=["*"]  默认全开，方便前端联调
- 生产环境：通过 .env 改成白名单，例：ALLOWED_ORIGINS=["https://yourdomain.com"]

单独抽出来而不是内联在 register_middlewares 里：
1. 配置和代码分离（12-Factor App 原则）
2. register_middlewares 只关心"注册顺序"，不关心"配置内容"
3. 不同环境可切换
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.infra.config import get_settings


def register_cors(app: FastAPI) -> None:
    """注册 CORS 中间件（配置从 Settings 读）"""
    s = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


__all__ = ["register_cors"]