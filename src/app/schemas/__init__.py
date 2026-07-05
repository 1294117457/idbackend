"""Pydantic 模型统一入口

按模块拆分：
- 通用分页容器：src/app/schemas/page
- 通用业务异常：src/app/schemas/errors
- 文件相关：src/app/schemas/file
- 模板分类：src/app/schemas/template_category
- 用户：src/app/schemas/user
- 角色：src/app/schemas/role
- 权限：src/app/schemas/permission
- 认证：src/app/schemas/auth
- 申请 / 模板 / 进度 / 附件：src/app/schemas/application / template / proof（其他模块暂保留内联）

外部使用：from src.app.schemas import ...，对实现位置无感知。
"""

# ========== 通用分页容器 ==========

from src.app.schemas.page import Page  # noqa: E402, F401

# ========== 通用业务异常（运行时层；非 Pydantic） ==========

from src.app.schemas.errors import (  # noqa: E402, F401
    BusinessError,
    NotFoundError,
    BadRequestError,
    ForbiddenError,
    ConflictError,
    UnauthorizedError,
)

# ========== 文件 ==========

from src.app.schemas.file import (  # noqa: E402, F401
    FileUploadRequest,
    FileAvatarUploadRequest,
    FileUpdateRequest,
    FileQueryRequest,
    FileVO,
    FileListVO,
    FileDataVO,
)

# ========== 模板分类 ==========

from src.app.schemas.template_category import (  # noqa: E402, F401
    TemplateCategoryCreateRequest,
    TemplateCategoryUpdateRequest,
    TemplateCategoryListQueryRequest,
    TemplateCategoryPageQueryRequest,
    TemplateCategoryVO,
    TemplateCategoryDetailVO,
    TemplateCategoryDeletePreviewVO,
    TemplateCategoryListVO,
)

# ========== 模板 / Rule / Attribute（v4） ==========

from src.app.schemas.template import (  # noqa: E402, F401
    RuleCreateRequest,
    RuleUpdateRequest,
    RuleVO,
    RuleDetailVO,
    AttributeCreateRequest,
    AttributeUpdateRequest,
    AttributeVO,
    AttributeListVO,
    TemplateCreateRequest,
    TemplateUpdateRequest,
    TemplateVO,
    TemplateDetailVO,
    TemplateListQueryRequest,
    TemplateListVO,
    TemplateCategoryListQueryRequest,
    TemplateBindRuleRequest,
    TemplateBindRuleResultVO,
    RuleBindAttributeRequest,
)

# ========== 用户 ==========

from src.app.schemas.user import (  # noqa: E402, F401
    UpdateProfileRequest,
    BindStudentRequest,
    UpdateStudentRequest,
    UpdateUserStatusRequest,
    CreateUserRequest,
    BatchCreateUserRequest,
    UserQueryRequest,
    UserProfileVO,
    UserCompleteInfoVO,
    UserStudentInfoVO,
    UserAdminListItemVO,
    UserAdminListVO,
    UserScoreVO,
    CurrentUserInfoVO,
)

# 别名：历史上 UserResponse = 当前最全的 UserCompleteInfoVO（兼容旧引用）
UserResponse = UserCompleteInfoVO

# ========== 角色 ==========

from src.app.schemas.role import (  # noqa: E402, F401
    RoleCreateRequest,
    RoleUpdateRequest,
    RolePermissionAssignRequest,
    RoleVO,
    RoleDetailVO,
    PermissionInRoleVO,
    RoleListVO,
)

# ========== 权限 ==========

from src.app.schemas.permission import (  # noqa: E402, F401
    PermissionCreateRequest,
    PermissionUpdateRequest,
    PermissionVO,
    PermissionListVO,
    ApiInterfaceVO,
    derive_module,
)

# ========== 认证 ==========

from src.app.schemas.auth import (  # noqa: E402, F401
    LoginRequest,
    RegisterRequest,
    SendCodeRequest,
    RefreshTokenRequest,
    LogoutRequest,
    ForgotPasswordRequest,
    AuthTokenPairVO,
    UserCreateResultVO,
    CaptchaVO,
)
