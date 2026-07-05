"""权限管理 DTO / VO

架构约定（与 file/template_category 一致）：
- Request 负责"接收输入 + 校验 + 提供转换方法（to_orm / apply_to）"
- VO      ：只做 ORM → 序列化投影，由 `from_orm_to_vo` 完成

约定：
- module 字段由 permissionCode 前缀派生（"user:read" → "user"），由 VO 内部处理
- status 字段：前端传 int 0/1，ORM 是 bool —— Request 内部转换
"""
from typing import Optional, List

from pydantic import BaseModel, Field, ConfigDict

from src.app.schemas.page import Page


# ========== 内部工具 ==========

def derive_module(permission_code: str) -> str:
    """从权限编码推导模块名（"module:action" → "module"）"""
    if ":" in permission_code:
        return permission_code.split(":", 1)[0]
    return ""


# ========== 请求 DTO ==========

class PermissionCreateRequest(BaseModel):
    """创建权限请求"""

    permissionCode: str = Field(..., min_length=1, max_length=100)
    permissionName: str = Field(..., min_length=1, max_length=100)
    module: Optional[str] = Field(default=None, description="模块名，不传则由 code 推导")
    apiPath: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, max_length=255)
    sortOrder: int = Field(default=0, ge=0)

    def to_orm(self) -> "Permission":
        from src.models.user import Permission

        return Permission(
            permission_code=self.permissionCode,
            permission_name=self.permissionName,
            api_path=self.apiPath,
            description=self.description,
            sort_order=self.sortOrder,
            status=True,
        )


class PermissionUpdateRequest(BaseModel):
    """更新权限请求（所有字段可选）"""

    model_config = ConfigDict(extra="forbid")

    id: int
    permissionCode: Optional[str] = Field(default=None, min_length=1, max_length=100)
    permissionName: Optional[str] = Field(default=None, min_length=1, max_length=100)
    module: Optional[str] = None
    apiPath: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, max_length=255)
    sortOrder: Optional[int] = Field(default=None, ge=0)
    status: Optional[int] = Field(default=None, description="0/1 整数")

    def apply_to(self, permission) -> bool:
        """把非空字段写回 ORM 对象。status: int → bool 转换。"""
        modified = False
        if self.permissionCode is not None:
            permission.permission_code = self.permissionCode
            modified = True
        if self.permissionName is not None:
            permission.permission_name = self.permissionName
            modified = True
        if self.apiPath is not None:
            permission.api_path = self.apiPath
            modified = True
        if self.description is not None:
            permission.description = self.description
            modified = True
        if self.sortOrder is not None:
            permission.sort_order = self.sortOrder
            modified = True
        if self.status is not None:
            permission.status = bool(self.status)
            modified = True
        return modified


# ========== 响应 VO ==========

class PermissionVO(BaseModel):
    """权限视图"""

    id: int
    permissionCode: str
    permissionName: str
    module: str = Field(default="", description="由 permissionCode 派生")
    apiPath: Optional[str]
    description: Optional[str]
    sortOrder: int
    status: int = Field(description="0/1")
    createdAt: Optional[str]
    updatedAt: Optional[str]

    @classmethod
    def from_orm_to_vo(cls, obj) -> "PermissionVO":
        return cls(
            id=obj.id,
            permissionCode=obj.permission_code,
            permissionName=obj.permission_name,
            module=derive_module(obj.permission_code),
            apiPath=obj.api_path,
            description=obj.description,
            sortOrder=obj.sort_order,
            status=1 if obj.status else 0,
            createdAt=str(obj.created_at) if obj.created_at else None,
            updatedAt=str(obj.updated_at) if obj.updated_at else None,
        )


class PermissionListVO(Page[PermissionVO]):
    """权限分页列表 VO（语义别名）"""

    pass


# ========== 接口扫描 VO（/interfaces） ==========

class ApiInterfaceVO(BaseModel):
    """FastAPI 路由扫描得到的接口视图"""

    path: str
    method: str
    code: str
    label: str

    @classmethod
    def from_route(cls, path: str, method: str, code: str) -> "ApiInterfaceVO":
        return cls(
            path=path,
            method=method,
            code=code,
            label=f"[{method}] {path}",
        )


__all__ = [
    "PermissionCreateRequest",
    "PermissionUpdateRequest",
    "PermissionVO",
    "PermissionListVO",
    "ApiInterfaceVO",
    "derive_module",
]
