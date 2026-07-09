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


# group_code / group_name 推导规则（与 migrations/015_permission_group.py 保持一致）
SORT_ORDER_GROUP_BUCKETS = [
    (200,   299, "user_admin",   "用户管理"),
    (300,   399, "role",         "角色管理"),
    (400,   499, "permission",   "权限管理"),
    (500,   599, "template",     "模板管理"),
    (700,   799, "rule",         "规则管理"),
    (900,   999, "system",       "系统配置"),
    (1000, 1099, "application",  "申请审核"),
    (1100, 1199, "proof",        "证明材料"),
]


def derive_group_code(api_path: Optional[str], permission_code: Optional[str], sort_order: Optional[int]) -> str:
    """按 sort_order 段位推导 group_code（与 migrations/015_permission_group.py 完全一致）。

    api_path / permission_code 在本规则下保留参数签名：
      - 当前规则只用 sort_order
      - 将来如果改动需要"按 code 前缀回退"，这两个参数继续可用
    """
    if sort_order is not None:
        for lo, hi, gc, _gn in SORT_ORDER_GROUP_BUCKETS:
            if lo <= sort_order <= hi:
                return gc
    return "other"


def derive_group_name(group_code: str) -> str:
    """group_code → 显示名（中文）。"""
    for lo, hi, gc, gn in SORT_ORDER_GROUP_BUCKETS:
        if gc == group_code:
            return gn
    return "其他"


# ========== 请求 DTO ==========

class PermissionCreateRequest(BaseModel):
    """创建权限请求"""

    permissionCode: str = Field(..., min_length=1, max_length=100)
    permissionName: str = Field(..., min_length=1, max_length=100)
    module: Optional[str] = Field(default=None, description="模块名，不传则由 code 推导")
    apiPath: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, max_length=255)
    sortOrder: int = Field(default=0, ge=0)
    # 分组（015 加；不传则后端由 api_path / permission_code 推导）
    groupCode: Optional[str] = Field(default=None, max_length=50)
    groupName: Optional[str] = Field(default=None, max_length=100)

    def to_orm(self) -> "Permission":
        from src.models.user import Permission

        from src.app.schemas.permission import derive_group_code as _gc
        from src.app.schemas.permission import derive_group_name as _gn

        resolved_gc = self.groupCode or _gc(self.apiPath, self.permissionCode, self.sortOrder)
        resolved_gn = self.groupName or _gn(resolved_gc)

        return Permission(
            permission_code=self.permissionCode,
            permission_name=self.permissionName,
            api_path=self.apiPath,
            description=self.description,
            sort_order=self.sortOrder,
            status=True,
            group_code=resolved_gc,
            group_name=resolved_gn,
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
    # 分组（015 加）
    groupCode: Optional[str] = Field(default=None, max_length=50)
    groupName: Optional[str] = Field(default=None, max_length=100)

    def apply_to(self, permission) -> bool:
        """把非空字段写回 ORM 对象。status: int → bool 转换。

        groupCode 一致性：若只改 groupCode 不改 groupName，自动 groupName = 该组已有。
        反过来：若只改 groupName 不改 groupCode，自动 groupCode = 同 groupName 的 code。
        这两个一致性规则由 service 在 update 前保证，schema 自身不做查询式一致性。
        """
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
        if self.groupCode is not None:
            permission.group_code = self.groupCode
            modified = True
            # 改了 groupCode 联动 groupName：用 caller 传入的 groupName，或按 group_code 推
            if self.groupName is not None:
                permission.group_name = self.groupName
            else:
                from src.app.schemas.permission import derive_group_name as _gn
                permission.group_name = _gn(self.groupCode)
        elif self.groupName is not None:
            # 只改了 groupName 不改 groupCode，保持 groupCode 不变，仅更新 groupName
            permission.group_name = self.groupName
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
    # 分组（015 加；老数据无 group 字段时回退 "other" / "其他"）
    groupCode: str = Field(default="other", description="分组技术 key")
    groupName: str = Field(default="其他", description="分组显示名")
    createdAt: Optional[str]
    updatedAt: Optional[str]

    @classmethod
    def from_orm_to_vo(cls, obj) -> "PermissionVO":
        gc = getattr(obj, "group_code", None) or "other"
        gn = getattr(obj, "group_name", None) or "其他"
        return cls(
            id=obj.id,
            permissionCode=obj.permission_code,
            permissionName=obj.permission_name,
            module=derive_module(obj.permission_code),
            apiPath=obj.api_path,
            description=obj.description,
            sortOrder=obj.sort_order,
            status=1 if obj.status else 0,
            groupCode=gc,
            groupName=gn,
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
    "derive_group_code",
    "derive_group_name",
    "SORT_ORDER_GROUP_BUCKETS",
]
