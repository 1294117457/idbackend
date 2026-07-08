"""Services 层"""
from src.services.auth_service import AuthService
from src.services.user_service import UserService
from src.services.user_profile_service import UserProfileService
from src.services.application_service import ApplicationService
from src.services.application_operation_service import ApplicationOperationService
from src.services.score_data_service import ScoreDataService
from src.services.template_service import TemplateService
from src.services.rule_service import RuleService
from src.services.attribute_service import AttributeService
from src.services.calculation_service import ScoreCalculationService
from src.services.template_category_service import TemplateCategoryService
from src.services.file_service import FileService
from src.services.rbac_service import RbacService

# ProofService 已废弃（proof 状态变更由 ApplicationService.review_proof 接管）
# 保留 import 以兼容旧路由——新代码不应再 import

__all__ = [
    "AuthService",
    "UserService",
    "UserProfileService",
    "ApplicationService",
    "ApplicationOperationService",
    "ScoreDataService",
    "TemplateService",
    "RuleService",
    "AttributeService",
    "ScoreCalculationService",
    "TemplateCategoryService",
    "FileService",
    "RbacService",
]