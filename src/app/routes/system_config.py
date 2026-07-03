"""系统配置 API

提供系统配置管理功能，仅 super_admin 可访问：
- GET /api/system/config - 获取系统配置
- PUT /api/system/config - 更新系统配置
- GET /api/system/config/agent - 获取 Agent 配置
- PUT /api/system/config/agent - 更新 Agent 配置
- GET /api/system/config/smtp - 获取 SMTP 配置
- PUT /api/system/config/smtp - 更新 SMTP 配置
"""
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional

from src.app.deps import get_db, get_current_user, CurrentUser
from src.app.response import success_response, error_response

router = APIRouter(prefix="/api/system/config", tags=["系统配置"])


class AgentConfig(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    chat_model: Optional[str] = None
    embedding_model: Optional[str] = None


class SmtpConfig(BaseModel):
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None


class SystemConfigUpdate(BaseModel):
    agent: Optional[AgentConfig] = None
    smtp: Optional[SmtpConfig] = None


@router.get("")
async def get_config(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取系统配置"""
    try:
        from src.infra.config import get_settings
        settings = get_settings()

        return success_response({
            "agent": {
                "api_key": settings.QWEN3_API_KEY[:4] + "****" if settings.QWEN3_API_KEY else "",
                "base_url": settings.QWEN_BASE_URL,
                "chat_model": settings.QWEN_CHAT_MODEL,
                "embedding_model": settings.QWEN_EMBEDDING_MODEL,
            },
            "smtp": {
                "smtp_host": settings.SMTP_HOST,
                "smtp_port": settings.SMTP_PORT,
                "smtp_username": settings.SMTP_USERNAME,
                "smtp_from": settings.SMTP_FROM,
            },
            "system_accounts": settings.SYSTEM_ACCOUNTS,
        })
    except Exception as e:
        return error_response(str(e))


@router.get("/agent")
async def get_agent_config(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取 Agent 配置"""
    try:
        from src.infra.config import get_settings
        settings = get_settings()

        return success_response({
            "api_key": settings.QWEN3_API_KEY[:4] + "****" if settings.QWEN3_API_KEY else "",
            "base_url": settings.QWEN_BASE_URL,
            "chat_model": settings.QWEN_CHAT_MODEL,
            "embedding_model": settings.QWEN_EMBEDDING_MODEL,
        })
    except Exception as e:
        return error_response(str(e))


@router.put("/agent")
async def update_agent_config(
    config: AgentConfig,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新 Agent 配置"""
    try:
        # 更新 .env 文件
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), ".env")

        with open(env_path, "r") as f:
            lines = f.readlines()

        updates = {
            "QWEN3_API_KEY": config.api_key,
            "QWEN_BASE_URL": config.base_url,
            "QWEN_CHAT_MODEL": config.chat_model,
            "QWEN_EMBEDDING_MODEL": config.embedding_model,
        }

        new_lines = []
        for line in lines:
            updated = False
            for key, value in updates.items():
                if value is not None and line.startswith(f"{key}="):
                    new_lines.append(f"{key}={value}\n")
                    updated = True
                    break
            if not updated:
                new_lines.append(line)

        with open(env_path, "w") as f:
            f.writelines(new_lines)

        return success_response({"message": "Agent 配置已更新，请重启服务生效"})
    except Exception as e:
        return error_response(str(e))


@router.get("/smtp")
async def get_smtp_config(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取 SMTP 配置"""
    try:
        from src.infra.config import get_settings
        settings = get_settings()

        return success_response({
            "smtp_host": settings.SMTP_HOST,
            "smtp_port": settings.SMTP_PORT,
            "smtp_username": settings.SMTP_USERNAME,
            "smtp_password": "****" if settings.SMTP_PASSWORD else "",
            "smtp_from": settings.SMTP_FROM,
        })
    except Exception as e:
        return error_response(str(e))


@router.put("/smtp")
async def update_smtp_config(
    config: SmtpConfig,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新 SMTP 配置"""
    try:
        # 更新 .env 文件
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), ".env")

        with open(env_path, "r") as f:
            lines = f.readlines()

        updates = {
            "SMTP_HOST": config.smtp_host,
            "SMTP_PORT": str(config.smtp_port) if config.smtp_port else None,
            "SMTP_USERNAME": config.smtp_username,
            "SMTP_PASSWORD": config.smtp_password,
            "SMTP_FROM": config.smtp_from,
        }

        new_lines = []
        for line in lines:
            updated = False
            for key, value in updates.items():
                if value is not None and line.startswith(f"{key}="):
                    new_lines.append(f"{key}={value}\n")
                    updated = True
                    break
            if not updated:
                new_lines.append(line)

        with open(env_path, "w") as f:
            f.writelines(new_lines)

        return success_response({"message": "SMTP 配置已更新"})
    except Exception as e:
        return error_response(str(e))
