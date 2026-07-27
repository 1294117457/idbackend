"""Models 层"""
from src.models.base import Base
from src.models.user import User, Role, Permission, UserRole, RolePermission
from src.models.application import (
    Application,
    ApplicationProof,
    ApplicationOperation,
    ApplicationStatus,
    ProofStatus,
    # Domain Events
    ApplicationEvent,
    ApplicationSubmitted,
    ApplicationCancelled,
    ApplicationRevoked,
    ApplicationApproved,
    ApplicationRejected,
)
from src.models.score_data import ScoreData
from src.models.template import (
    Template,
    Rule,
    Attribute,
    TemplateRule,
    RuleAttribute,
    AttributeType,
)
from src.models.template_category import TemplateCategory
from src.models.extra_info_field import ExtraInfoField
from src.models.file import FileMetadata, FileCategory
from src.models.embedding import Embedding, EmbeddingCategory
from src.models.system_config import SystemConfig
from src.models.ai_chat import (
    AgentSession,
    AgentMessage,
    AgentSessionSummary,
    AgentSessionSnapshot,
    SessionStatus,
    MessageRole,
    MessageType,
)

__all__ = [
    "Base",
    # User
    "User",
    "Role",
    "Permission",
    "UserRole",
    "RolePermission",
    # Application
    "Application",
    "ApplicationProof",
    "ApplicationOperation",
    "ApplicationStatus",
    "ProofStatus",
    # Domain Events
    "ApplicationEvent",
    "ApplicationSubmitted",
    "ApplicationCancelled",
    "ApplicationRevoked",
    "ApplicationApproved",
    "ApplicationRejected",
    # ScoreData
    "ScoreData",
    # Template（v4：5 张表 + 共享枚举）
    "Template",
    "Rule",
    "Attribute",
    "TemplateRule",
    "RuleAttribute",
    "AttributeType",
    # Template Category (Layer 1)
    "TemplateCategory",
    # Extra Info Field
    "ExtraInfoField",
    # File
    "FileMetadata",
    "FileCategory",
    # Embedding
    "Embedding",
    "EmbeddingCategory",
    # Config
    "SystemConfig",
    # AI Chat
    "AgentSession",
    "AgentMessage",
    "AgentSessionSummary",
    "AgentSessionSnapshot",
    "SessionStatus",
    "MessageRole",
    "MessageType",
]