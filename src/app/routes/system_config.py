"""系统配置 API

提供系统配置管理功能，仅 super_admin 可访问：
- GET /api/system/config - 获取全量配置
- GET /api/system/config/rag - 获取 RAG 搜索配置
- PUT /api/system/config/rag - 更新 RAG 搜索配置
- GET /api/system/config/llm - 获取 LLM 配置
- PUT /api/system/config/llm - 更新 LLM 配置
- GET /api/system/config/embed - 获取 Embedding 配置
- PUT /api/system/config/embed - 更新 Embedding 配置
- GET /api/system/config/smtp - 获取 SMTP 配置
- PUT /api/system/config/smtp - 更新 SMTP 配置
- POST /api/system/config/rbac/reset - 重置 RBAC

所有运行时配置（LLM/Embed/SMTP/RAG）优先从 DB 读取，DB 无记录时回退到 .env。
PUT 后会自动刷新 config.py 中的运行时缓存。
"""

from fastapi import APIRouter

from src.app import response as R
from src.infra.database import AsyncSessionLocal
from src.services.system_config_service import SystemConfigService
from src.app.schemas.system_config import (
    LlmConfigRequest,
    EmbedConfigRequest,
    SmtpConfigRequest,
    RagSearchConfigRequest,
    LlmEmbedConfigRequest,
)

router = APIRouter(prefix="/api/system/config", tags=["系统配置"])


# ============================================================
# 全量配置
# ============================================================

@router.get("")
async def get_all_config():
    """获取全量系统配置（敏感字段脱敏）"""
    async with AsyncSessionLocal() as db:
        data = await SystemConfigService.get_all_config(db)
    return R.query_resp(data)


# ============================================================
# RAG 配置
# ============================================================

@router.get("/rag")
async def get_rag_config():
    """获取 RAG 搜索配置（敏感字段脱敏）"""
    async with AsyncSessionLocal() as db:
        data = await SystemConfigService.get_rag_config(db)
    return R.query_resp(data)


@router.put("/rag")
async def update_rag_config(req: RagSearchConfigRequest):
    """更新 RAG 搜索配置"""
    async with AsyncSessionLocal() as db:
        data = await SystemConfigService.update_rag_config(db, req.model_dump(exclude_none=True))
    return R.success_resp(data, msg="RAG 配置已更新")


# ============================================================
# LLM 配置
# ============================================================

@router.get("/llm")
async def get_llm_config():
    """获取 LLM 配置（敏感字段脱敏）"""
    async with AsyncSessionLocal() as db:
        data = await SystemConfigService.get_llm_config(db)
    return R.query_resp(data)


@router.put("/llm")
async def update_llm_config(req: LlmConfigRequest):
    """更新 LLM 配置（敏感字段以明文存储，GET 时脱敏返回）"""
    async with AsyncSessionLocal() as db:
        data = await SystemConfigService.update_llm_config(db, req.model_dump(exclude_none=True))
    return R.success_resp(data, msg="LLM 配置已更新")


# ============================================================
# Agent（LLM + Embedding 合并，前端专用）
# ============================================================

@router.get("/agent")
async def get_agent_config():
    """获取 Agent 配置（LLM + Embedding 合并，敏感字段脱敏）"""
    async with AsyncSessionLocal() as db:
        llm = await SystemConfigService.get_llm_config(db)
        embed = await SystemConfigService.get_embed_config(db)
    return R.query_resp({
        "provider": llm.get("provider"),
        "api_key": llm.get("api_key", ""),
        "base_url": llm.get("base_url"),
        "chat_model": llm.get("chat_model"),
        "embedding_api_key": embed.get("api_key", ""),
        "embedding_base_url": embed.get("base_url"),
        "embedding_model": embed.get("model"),
        "embedding_dim": embed.get("dim"),
    })


@router.put("/agent")
async def update_agent_config(req: LlmEmbedConfigRequest):
    """更新 Agent 配置（拆分到 LLM + Embedding）"""
    async with AsyncSessionLocal() as db:
        llm_data = req.model_dump(exclude_none=True)
        embed_data = {
            "api_key": llm_data.pop("embedding_api_key", None),
            "base_url": llm_data.pop("embedding_base_url", None),
            "model": llm_data.pop("embedding_model", None),
            "dim": llm_data.pop("embedding_dim", None),
        }
        # 去掉空值
        llm_data = {k: v for k, v in llm_data.items() if v is not None}
        embed_data = {k: v for k, v in embed_data.items() if v is not None}
        if llm_data:
            await SystemConfigService.update_llm_config(db, llm_data)
        if embed_data:
            await SystemConfigService.update_embed_config(db, embed_data)
    return R.success_resp(msg="Agent 配置已更新")


# ============================================================
# Embedding 配置
# ============================================================

@router.get("/embed")
async def get_embed_config():
    """获取 Embedding 配置（敏感字段脱敏）"""
    async with AsyncSessionLocal() as db:
        data = await SystemConfigService.get_embed_config(db)
    return R.query_resp(data)


@router.put("/embed")
async def update_embed_config(req: EmbedConfigRequest):
    """更新 Embedding 配置（敏感字段以明文存储，GET 时脱敏返回）"""
    async with AsyncSessionLocal() as db:
        data = await SystemConfigService.update_embed_config(db, req.model_dump(exclude_none=True))
    return R.success_resp(data, msg="Embedding 配置已更新")


# ============================================================
# SMTP 配置
# ============================================================

@router.get("/smtp")
async def get_smtp_config():
    """获取 SMTP 配置（敏感字段脱敏）"""
    async with AsyncSessionLocal() as db:
        data = await SystemConfigService.get_smtp_config(db)
    return R.query_resp(data)


@router.put("/smtp")
async def update_smtp_config(req: SmtpConfigRequest):
    """更新 SMTP 配置（敏感字段以明文存储，GET 时脱敏返回）"""
    async with AsyncSessionLocal() as db:
        data = await SystemConfigService.update_smtp_config(db, req.model_dump(exclude_none=True))
    return R.success_resp(data, msg="SMTP 配置已更新")


# ============================================================
# RBAC 重置
# ============================================================

@router.post("/rbac/reset")
async def reset_rbac():
    """硬重置 RBAC：清空 role_permission / user_role + 删除 seed 维护的 role / permission → 重新 seed。"""
    from src.scripts.init_rbac_data import reset_rbac_data
    from src.services.rbac_service import RbacService

    stats = await reset_rbac_data()
    await RbacService.invalidate_all_user_caches()
    return R.success_resp({
        "message": "RBAC 已重置",
        "stats": stats,
    }, msg="RBAC 已重置")
