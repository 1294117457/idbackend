"""SystemConfig Pydantic Schema

RequestDTO / VO 集中定义：
- 敏感字段在 VO 层脱敏，service 层直接返回 ORM 对象
- 枚举归一化在 schema 层处理
"""

from typing import Optional, List, Any, Dict

from pydantic import BaseModel, Field


# ============================================================
# 枚举定义（供 Request / Response 共用）
# ============================================================

class ConfigCategory(str):
    """配置分类枚举（与 models.system_config.ConfigCategory 保持一致）"""
    RAG = "RAG"
    LLM = "LLM"
    EMBED = "EMBED"
    SMTP = "SMTP"
    AGENT = "AGENT"
    OTHER = "OTHER"


class ConfigValueType(str):
    """配置值类型枚举（与 models.system_config.ConfigValueType 保持一致）"""
    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    JSON = "json"


# ============================================================
# RAG 搜索配置
# ============================================================

class RagSearchConfigRequest(BaseModel):
    """RAG 搜索配置更新请求"""
    search_mode: Optional[str] = None
    candidate_k: Optional[int] = None
    rrf_k: Optional[int] = None
    source_discount: Optional[float] = None
    bm25_rank1_weight: Optional[float] = None
    top_k: Optional[int] = None
    hybrid_weight: Optional[float] = None


class RagSearchConfigVO(BaseModel):
    """RAG 搜索配置响应 VO（敏感字段脱敏）"""
    search_mode: Optional[str] = None
    candidate_k: Optional[int] = None
    rrf_k: Optional[int] = None
    source_discount: Optional[float] = None
    bm25_rank1_weight: Optional[float] = None
    top_k: Optional[int] = None
    hybrid_weight: Optional[float] = None


# ============================================================
# LLM / Embedding 配置
# ============================================================

class LlmConfigRequest(BaseModel):
    """LLM 配置更新请求"""
    provider: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    chat_model: Optional[str] = None


class LlmConfigVO(BaseModel):
    """LLM 配置响应 VO（敏感字段脱敏）"""
    provider: Optional[str] = None
    api_key: str = ""  # 敏感字段，GET 时脱敏
    base_url: Optional[str] = None
    chat_model: Optional[str] = None


class EmbedConfigRequest(BaseModel):
    """Embedding 配置更新请求"""
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    dim: Optional[int] = None


class EmbedConfigVO(BaseModel):
    """Embedding 配置响应 VO（敏感字段脱敏）"""
    api_key: str = ""  # 敏感字段，GET 时脱敏
    base_url: Optional[str] = None
    model: Optional[str] = None
    dim: Optional[int] = None


# ============================================================
# SMTP 配置
# ============================================================

class SmtpConfigRequest(BaseModel):
    """SMTP 配置更新请求"""
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    from_addr: Optional[str] = None


class SmtpConfigVO(BaseModel):
    """SMTP 配置响应 VO（敏感字段脱敏）"""
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: str = ""  # 敏感字段，GET 时脱敏
    from_addr: Optional[str] = None


# ============================================================
# 单条配置（通用）
# ============================================================

class ConfigItemVO(BaseModel):
    """单条配置项 VO"""
    config_key: str
    config_value: str  # 敏感字段已在 service 层脱敏
    description: Optional[str] = None
    category: str
    value_type: str
    is_sensitive: bool


class ConfigItemRequest(BaseModel):
    """单条配置更新请求"""
    config_key: str
    config_value: str
    description: Optional[str] = None
    category: str = "OTHER"
    value_type: str = "string"
    is_sensitive: bool = False


class ConfigListVO(BaseModel):
    """配置列表响应"""
    items: List[ConfigItemVO]
    total: int


# ============================================================
# 全量配置（聚合）
# ============================================================

class SystemConfigVO(BaseModel):
    """系统全量配置 VO（分组展示）"""
    rag: Optional[RagSearchConfigVO] = None
    llm: Optional[LlmConfigVO] = None
    embed: Optional[EmbedConfigVO] = None
    smtp: Optional[SmtpConfigVO] = None


# ============================================================
# 类型转换工具
# ============================================================

def cast_config_value(value: str, value_type: str) -> Any:
    """根据 value_type 将字符串转为对应类型"""
    if value_type == ConfigValueType.INT:
        return int(value)
    if value_type == ConfigValueType.FLOAT:
        return float(value)
    if value_type == ConfigValueType.BOOL:
        return value.lower() in ("true", "1", "yes")
    if value_type == ConfigValueType.JSON:
        import json
        return json.loads(value)
    return value


# ========== Agent（LLM + Embedding 合并接口）==========
# 前端 /agent Tab 使用，后端内部调用 LLM + Embed 分开存储


class LlmEmbedConfigRequest(BaseModel):
    """Agent 配置更新请求（LLM + Embedding 合并）"""
    # LLM 字段
    provider: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    chat_model: Optional[str] = None
    # Embedding 字段
    embedding_api_key: Optional[str] = None
    embedding_base_url: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_dim: Optional[int] = None


class LlmEmbedConfigVO(BaseModel):
    """Agent 配置响应 VO（敏感字段脱敏）"""
    # LLM
    provider: Optional[str] = None
    api_key: str = ""  # 敏感字段，GET 时脱敏
    base_url: Optional[str] = None
    chat_model: Optional[str] = None
    # Embedding
    embedding_api_key: str = ""  # 敏感字段，GET 时脱敏
    embedding_base_url: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_dim: Optional[int] = None


# ============================================================
# 配置 key 常量（与 DB system_config 表 config_key 列对应）
# ============================================================

class RagConfigKeys:
    """RAG 搜索配置对应的 config_key"""
    SEARCH_MODE = "RAG_SEARCH_MODE"
    CANDIDATE_K = "RAG_CANDIDATE_K"
    RRF_K = "RAG_RRF_K"
    SOURCE_DISCOUNT = "RAG_SOURCE_DISCOUNT"
    BM25_RANK1_WEIGHT = "RAG_BM25_RANK1_WEIGHT"
    TOP_K = "RAG_TOP_K"
    HYBRID_WEIGHT = "RAG_HYBRID_WEIGHT"

    @classmethod
    def all_keys(cls) -> List[str]:
        return [
            cls.SEARCH_MODE, cls.CANDIDATE_K, cls.RRF_K,
            cls.SOURCE_DISCOUNT, cls.BM25_RANK1_WEIGHT,
            cls.TOP_K, cls.HYBRID_WEIGHT,
        ]


class LlmConfigKeys:
    """LLM 配置对应的 config_key"""
    PROVIDER = "LLM_PROVIDER"
    API_KEY = "LLM_API_KEY"
    BASE_URL = "LLM_BASE_URL"
    CHAT_MODEL = "LLM_CHAT_MODEL"

    @classmethod
    def all_keys(cls) -> List[str]:
        return [cls.PROVIDER, cls.API_KEY, cls.BASE_URL, cls.CHAT_MODEL]


class EmbedConfigKeys:
    """Embedding 配置对应的 config_key"""
    API_KEY = "EMBED_API_KEY"
    BASE_URL = "EMBED_BASE_URL"
    MODEL = "EMBED_MODEL"
    DIM = "EMBED_DIM"

    @classmethod
    def all_keys(cls) -> List[str]:
        return [cls.API_KEY, cls.BASE_URL, cls.MODEL, cls.DIM]


class SmtpConfigKeys:
    """SMTP 配置对应的 config_key"""
    HOST = "SMTP_HOST"
    PORT = "SMTP_PORT"
    USERNAME = "SMTP_USERNAME"
    PASSWORD = "SMTP_PASSWORD"
    FROM_ADDR = "SMTP_FROM"

    @classmethod
    def all_keys(cls) -> List[str]:
        return [cls.HOST, cls.PORT, cls.USERNAME, cls.PASSWORD, cls.FROM_ADDR]


def mask_sensitive(value: Optional[str]) -> str:
    """敏感字段脱敏"""
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return value[:4] + "****"
