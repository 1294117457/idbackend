"""SystemConfig 服务层

职责：
- 业务规则处理（配置映射、类型转换、脱敏）
- 调用 SystemConfigRepository 完成数据库操作
- 异常统一抛出（NotFoundError / BadRequestError）

配置更新后自动刷新缓存，无需手动调用 refresh_cache。
"""

from typing import Optional, List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.schemas.errors import NotFoundError, BadRequestError
from src.app.schemas.system_config import (
    cast_config_value,
    mask_sensitive,
    ConfigCategory,
    ConfigValueType,
    RagConfigKeys,
    LlmConfigKeys,
    EmbedConfigKeys,
    SmtpConfigKeys,
)
from src.repositories.system_config_repo import SystemConfigRepository

class SystemConfigService:
    """SystemConfig 服务（Layer 2）"""

    # ---------- 内部工具 ----------

    @staticmethod
    def _map_to_rag_dict(rows: Dict[str, Any]) -> Dict[str, Any]:
        """将 DB rows 映射为 RAG 配置字典

        字段分组：
        - 召回参数：top_k / candidate_k / min_score
        - 融合权重：vector_weight / bm25_weight / single_source_penalty / same_doc_decay
        """
        return {
            # 召回参数
            "top_k": rows.get(RagConfigKeys.TOP_K),
            "candidate_k": rows.get(RagConfigKeys.CANDIDATE_K),
            "min_score": rows.get(RagConfigKeys.MIN_SCORE),
            # 融合权重
            "vector_weight": rows.get(RagConfigKeys.VECTOR_WEIGHT),
            "bm25_weight": rows.get(RagConfigKeys.BM25_WEIGHT),
            "single_source_penalty": rows.get(RagConfigKeys.SINGLE_SOURCE_PENALTY),
            "same_doc_decay": rows.get(RagConfigKeys.SAME_DOC_DECAY),
        }

    @staticmethod
    def _map_to_llm_dict(rows: Dict[str, Any]) -> Dict[str, Any]:
        """将 DB rows 映射为 LLM 配置字典"""
        return {
            "provider": rows.get(LlmConfigKeys.PROVIDER),
            "api_key": rows.get(LlmConfigKeys.API_KEY),
            "base_url": rows.get(LlmConfigKeys.BASE_URL),
            "chat_model": rows.get(LlmConfigKeys.CHAT_MODEL),
        }

    @staticmethod
    def _map_to_embed_dict(rows: Dict[str, Any]) -> Dict[str, Any]:
        """将 DB rows 映射为 Embedding 配置字典"""
        return {
            "api_key": rows.get(EmbedConfigKeys.API_KEY),
            "base_url": rows.get(EmbedConfigKeys.BASE_URL),
            "model": rows.get(EmbedConfigKeys.MODEL),
            "dim": rows.get(EmbedConfigKeys.DIM),
        }

    @staticmethod
    def _map_to_smtp_dict(rows: Dict[str, Any]) -> Dict[str, Any]:
        """将 DB rows 映射为 SMTP 配置字典"""
        return {
            "host": rows.get(SmtpConfigKeys.HOST),
            "port": rows.get(SmtpConfigKeys.PORT),
            "username": rows.get(SmtpConfigKeys.USERNAME),
            "password": rows.get(SmtpConfigKeys.PASSWORD),
            "from_addr": rows.get(SmtpConfigKeys.FROM_ADDR),
        }

    # ---------- 读（带脱敏） ----------

    @staticmethod
    async def _fetch_raw(db: AsyncSession, config_keys: List[str]) -> Dict[str, Any]:
        """从 DB 批量查询原始值，返回 {key: value}"""
        rows = await SystemConfigRepository.list_keys(db, config_keys)
        result = {}
        for row in rows:
            result[row.config_key] = cast_config_value(row.config_value, row.value_type)
        return result

    @staticmethod
    async def _fetch_with_sensitive_mask(db: AsyncSession, config_keys: List[str]) -> Dict[str, Any]:
        """从 DB 批量查询，敏感字段脱敏，返回 {key: masked_value}"""
        rows = await SystemConfigRepository.list_keys(db, config_keys)
        result = {}
        for row in rows:
            if row.is_sensitive:
                result[row.config_key] = mask_sensitive(row.config_value)
            else:
                result[row.config_key] = cast_config_value(row.config_value, row.value_type)
        return result

    # ---------- 读 API ----------

    @staticmethod
    async def get_rag_config(db: AsyncSession) -> Dict[str, Any]:
        """获取 RAG 搜索配置（敏感字段脱敏）"""
        rows = await SystemConfigService._fetch_with_sensitive_mask(db, RagConfigKeys.all_keys())
        return SystemConfigService._map_to_rag_dict(rows)

    @staticmethod
    async def get_llm_config(db: AsyncSession) -> Dict[str, Any]:
        """获取 LLM 配置（敏感字段脱敏）"""
        rows = await SystemConfigService._fetch_with_sensitive_mask(db, LlmConfigKeys.all_keys())
        return SystemConfigService._map_to_llm_dict(rows)

    @staticmethod
    async def get_embed_config(db: AsyncSession) -> Dict[str, Any]:
        """获取 Embedding 配置（敏感字段脱敏）"""
        rows = await SystemConfigService._fetch_with_sensitive_mask(db, EmbedConfigKeys.all_keys())
        return SystemConfigService._map_to_embed_dict(rows)

    @staticmethod
    async def get_smtp_config(db: AsyncSession) -> Dict[str, Any]:
        """获取 SMTP 配置（敏感字段脱敏）"""
        rows = await SystemConfigService._fetch_with_sensitive_mask(db, SmtpConfigKeys.all_keys())
        return SystemConfigService._map_to_smtp_dict(rows)

    @staticmethod
    async def get_all_config(db: AsyncSession) -> Dict[str, Any]:
        """获取全量配置（敏感字段脱敏）"""
        all_keys = (
            RagConfigKeys.all_keys()
            + LlmConfigKeys.all_keys()
            + EmbedConfigKeys.all_keys()
            + SmtpConfigKeys.all_keys()
        )
        rows = await SystemConfigService._fetch_with_sensitive_mask(db, all_keys)
        return {
            "rag": SystemConfigService._map_to_rag_dict(rows),
            "llm": SystemConfigService._map_to_llm_dict(rows),
            "embed": SystemConfigService._map_to_embed_dict(rows),
            "smtp": SystemConfigService._map_to_smtp_dict(rows),
        }

    # ---------- 写 API ----------

    @staticmethod
    async def update_rag_config(db: AsyncSession, config: Dict[str, Any]) -> Dict[str, Any]:
        """更新 RAG 配置

        字段分组：
        - 召回参数：top_k(int) / candidate_k(int) / min_score(float)
        - 融合权重：vector_weight(float) / bm25_weight(float) / single_source_penalty(float) / same_doc_decay(float)
        """
        mappings = [
            # 召回参数
            (RagConfigKeys.TOP_K, "top_k", "int"),
            (RagConfigKeys.CANDIDATE_K, "candidate_k", "int"),
            (RagConfigKeys.MIN_SCORE, "min_score", "float"),
            # 融合权重
            (RagConfigKeys.VECTOR_WEIGHT, "vector_weight", "float"),
            (RagConfigKeys.BM25_WEIGHT, "bm25_weight", "float"),
            (RagConfigKeys.SINGLE_SOURCE_PENALTY, "single_source_penalty", "float"),
            (RagConfigKeys.SAME_DOC_DECAY, "same_doc_decay", "float"),
        ]
        for key, field, value_type in mappings:
            if field in config and config[field] is not None:
                await SystemConfigRepository.upsert(
                    db,
                    config_key=key,
                    config_value=str(config[field]),
                    category=ConfigCategory.RAG,
                    value_type=value_type,
                    description=f"RAG 搜索参数: {field}",
                )
        await db.commit()
        result = await SystemConfigService.get_rag_config(db)
        from src.infra.config import refresh_cache
        await refresh_cache(db)
        return result

    @staticmethod
    async def update_llm_config(db: AsyncSession, config: Dict[str, Any]) -> Dict[str, Any]:
        """更新 LLM 配置"""
        mappings = [
            (LlmConfigKeys.PROVIDER, "provider", "string"),
            (LlmConfigKeys.API_KEY, "api_key", "string", True),  # 敏感字段
            (LlmConfigKeys.BASE_URL, "base_url", "string"),
            (LlmConfigKeys.CHAT_MODEL, "chat_model", "string"),
        ]
        for item in mappings:
            key, field, value_type = item[0], item[1], item[2]
            is_sensitive = item[3] if len(item) > 3 else False
            if field in config and config[field] is not None:
                await SystemConfigRepository.upsert(
                    db,
                    config_key=key,
                    config_value=str(config[field]),
                    category=ConfigCategory.LLM,
                    value_type=value_type,
                    is_sensitive=is_sensitive,
                    description=f"LLM 配置: {field}",
                )
        await db.commit()
        result = await SystemConfigService.get_llm_config(db)
        from src.infra.config import refresh_cache
        await refresh_cache(db)
        return result

    @staticmethod
    async def update_embed_config(db: AsyncSession, config: Dict[str, Any]) -> Dict[str, Any]:
        """更新 Embedding 配置"""
        mappings = [
            (EmbedConfigKeys.API_KEY, "api_key", "string", True),  # 敏感字段
            (EmbedConfigKeys.BASE_URL, "base_url", "string"),
            (EmbedConfigKeys.MODEL, "model", "string"),
            (EmbedConfigKeys.DIM, "dim", "int"),
        ]
        for item in mappings:
            key, field, value_type = item[0], item[1], item[2]
            is_sensitive = item[3] if len(item) > 3 else False
            if field in config and config[field] is not None:
                await SystemConfigRepository.upsert(
                    db,
                    config_key=key,
                    config_value=str(config[field]),
                    category=ConfigCategory.EMBED,
                    value_type=value_type,
                    is_sensitive=is_sensitive,
                    description=f"Embedding 配置: {field}",
                )
        await db.commit()
        result = await SystemConfigService.get_embed_config(db)
        from src.infra.config import refresh_cache
        await refresh_cache(db)
        return result

    @staticmethod
    async def update_smtp_config(db: AsyncSession, config: Dict[str, Any]) -> Dict[str, Any]:
        """更新 SMTP 配置"""
        mappings = [
            (SmtpConfigKeys.HOST, "host", "string"),
            (SmtpConfigKeys.PORT, "port", "int"),
            (SmtpConfigKeys.USERNAME, "username", "string"),
            (SmtpConfigKeys.PASSWORD, "password", "string", True),  # 敏感字段
            (SmtpConfigKeys.FROM_ADDR, "from_addr", "string"),
        ]
        for item in mappings:
            key, field, value_type = item[0], item[1], item[2]
            is_sensitive = item[3] if len(item) > 3 else False
            if field in config and config[field] is not None:
                await SystemConfigRepository.upsert(
                    db,
                    config_key=key,
                    config_value=str(config[field]),
                    category=ConfigCategory.SMTP,
                    value_type=value_type,
                    is_sensitive=is_sensitive,
                    description=f"SMTP 配置: {field}",
                )
        await db.commit()
        result = await SystemConfigService.get_smtp_config(db)
        from src.infra.config import refresh_cache
        await refresh_cache(db)
        return result

    # ---------- 通用 ----------

    @staticmethod
    async def get_config_raw(db: AsyncSession, config_key: str) -> Optional[Any]:
        """获取单个配置原始值（内部使用，不脱敏）"""
        row = await SystemConfigRepository.get_by_key(db, config_key)
        if not row:
            return None
        return cast_config_value(row.config_value, row.value_type)

    @staticmethod
    async def upsert_config(
        db: AsyncSession,
        config_key: str,
        config_value: str,
        *,
        description: Optional[str] = None,
        category: str = ConfigCategory.OTHER,
        value_type: str = ConfigValueType.STRING,
        is_sensitive: bool = False,
    ) -> None:
        """通用 UPSERT 配置"""
        await SystemConfigRepository.upsert(
            db,
            config_key=config_key,
            config_value=config_value,
            description=description,
            category=category,
            value_type=value_type,
            is_sensitive=is_sensitive,
        )

    @staticmethod
    async def list_by_category(db: AsyncSession, category: str) -> List[Any]:
        """按分类查询配置"""
        rows = await SystemConfigRepository.list_by_category(db, category)
        return rows
