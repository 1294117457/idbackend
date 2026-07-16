"""Services 层"""
from src.services.auth_service import AuthService
from src.services.user_service import UserService
from src.services.application_service import ApplicationService
from src.services.score_data_service import ScoreDataService
from src.services.template_service import TemplateService
from src.services.rule_service import RuleService
from src.services.attribute_service import AttributeService
from src.services.calculation_service import ScoreCalculationService
from src.services.template_category_service import TemplateCategoryService
from src.services.file_service import FileService
from src.services.rbac_service import RbacService

# ProofService、ApplicationOperationService 已废弃（已合并到 ApplicationService）
# UserProfileService 已合并到 UserService

__all__ = [
    "AuthService",
    "UserService",
    "ApplicationService",
    "ScoreDataService",
    "TemplateService",
    "RuleService",
    "AttributeService",
    "ScoreCalculationService",
    "TemplateCategoryService",
    "FileService",
    "RbacService",
]