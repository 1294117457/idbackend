"""Repositories 层（数据访问层）"""
from src.repositories.template_category_repo import TemplateCategoryRepository
from src.repositories.template_repo import TemplateRepository
from src.repositories.rule_repo import RuleRepository
from src.repositories.attribute_repo import AttributeRepository
from src.repositories.application_repo import ApplicationRepository
from src.repositories.embedding_repo import EmbeddingRepository
from src.repositories.ai_chat_repo import AIChatRepository
from src.repositories.user_repo import UserRepository
from src.repositories.role_repo import RoleRepository
from src.repositories.permission_repo import PermissionRepository

__all__ = [
    "TemplateCategoryRepository",
    "TemplateRepository",
    "RuleRepository",
    "AttributeRepository",
    "ApplicationRepository",
    "EmbeddingRepository",
    "AIChatRepository",
    "UserRepository",
    "RoleRepository",
    "PermissionRepository",
]
