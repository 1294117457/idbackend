"""角色管理 DTO / VO

架构约定（与 file/template_category 一致）：
- Request 负责"接收输入 + 校验 + 提供转换方法（to_orm / apply_to）"
- VO      ：只做 ORM → 序列化投影，由 `from_orm_to_vo` 完成

约定：
- status 字段：前端传 int 0/1，ORM 是 bool —— Request 内部转换
"""
from typing import Optional, List

from pydantic import BaseModel, Field, ConfigDict

from src.app.schemas.page import Page


# ========== 请求 DTO ==========

class RoleCreateRequest(BaseModel):
    """创建角色请求"""

    roleCode: str = Field(..., min_length=1, max_length=50)
    roleName: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=255)
    sortOrder: int = Field(default=0, ge=0)

    def to_orm(self) -> "Role":
        from src.models.user import Role

        return Role(
            role_code=self.roleCode,
            role_name=self.roleName,
            description=self.description,
            sort_order=self.sortOrder,
            status=True,
            is_system=False,
        )


class RoleUpdateRequest(BaseModel):
    """更新角色请求（所有字段可选）"""

    model_config = ConfigDict(extra="forbid")

    id: int
    roleCode: Optional[str] = Field(default=None, min_length=1, max_length=50)
    roleName: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=255)
    sortOrder: Optional[int] = Field(default=None, ge=0)
    status: Optional[int] = Field(default=None, description="0/1 整数")

    def apply_to(self, role) -> bool:
        """把非空字段写回 ORM 对象。status: int → bool 转换。"""
        modified = False
        if self.roleCode is not None:
            role.role_code = self.roleCode
            modified = True
        if self.roleName is not None:
            role.role_name = self.roleName
            modified = True
        if self.description is not None:
            role.description = self.description
            modified = True
        if self.sortOrder is not None:
            role.sort_order = self.sortOrder
            modified = True
        if self.status is not None:
            role.status = bool(self.status)
            modified = True
        return modified


class RoleDeleteRequest(BaseModel):
    """删除角色请求（POST /delete）"""

    id: int = Field(..., ge=1)


class RolePermissionAssignRequest(BaseModel):
    """为角色分配权限"""

    roleId: int
    permissionIds: List[int]


# ========== 响应 VO ==========

class RoleVO(BaseModel):
    """角色视图（不带 permissions 子表）"""

    id: int
    roleCode: str
    roleName: str
    description: Optional[str]
    sortOrder: int
    status: int = Field(description="0/1，前端约定")
    isSystem: int = Field(description="0/1，前端约定")
    createdAt: Optional[str]
    updatedAt: Optional[str]

    @classmethod
    def from_orm_to_vo(cls, role) -> "RoleVO":
        return cls(
            id=role.id,
            roleCode=role.role_code,
            roleName=role.role_name,
            description=role.description,
            sortOrder=role.sort_order,
            status=1 if role.status else 0,
            isSystem=1 if role.is_system else 0,
            createdAt=str(role.created_at) if role.created_at else None,
            updatedAt=str(role.updated_at) if role.updated_at else None,
        )


class RoleDetailVO(RoleVO):
    """角色详情（含已分配权限列表）"""

    permissions: List["PermissionInRoleVO"] = Field(default_factory=list)

    @classmethod
    def from_orm_to_vo(cls, role, permissions: List["PermissionVO"]) -> "RoleDetailVO":
        base = RoleVO.from_orm_to_vo(role).model_dump()
        return cls(**base, permissions=[PermissionInRoleVO.from_orm_to_vo(p) for p in permissions])


class PermissionInRoleVO(BaseModel):
    """角色详情中嵌套的权限视图（字段精简）"""

    id: int
    permissionCode: str
    permissionName: str
    routePath: Optional[str]
    description: Optional[str]

    @classmethod
    def from_orm_to_vo(cls, p) -> "PermissionInRoleVO":
        return cls(
            id=p.id,
            permissionCode=p.permission_code,
            permissionName=p.permission_name,
            routePath=p.api_path,
            description=p.description,
        )


class RoleListVO(Page[RoleVO]):
    """角色分页列表 VO"""

    pass


__all__ = [
    "RoleCreateRequest",
    "RoleUpdateRequest",
    "RoleDeleteRequest",
    "RolePermissionAssignRequest",
    "RoleVO",
    "RoleDetailVO",
    "PermissionInRoleVO",
    "RoleListVO",
]
