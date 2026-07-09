"""ExtraInfoField DTO / VO

架构约定：
- Request 负责"接收输入 + 校验 + 提供转换方法（to_orm / apply_to）"
- VO 只做 ORM → 序列化投影，集中由 `from_orm_to_vo` 完成
- 列表场景使用 Page[T] / XXXListVO(Page[T]) 模式
"""
from typing import Optional, List, Literal

from pydantic import BaseModel, Field, ConfigDict

from src.app.schemas.page import Page


# ========== 允许的字段类型 ==========

FIELD_TYPES = Literal["TEXT", "NUMBER", "SELECT", "DATE"]


# ========== 请求 DTO ==========

class ExtraInfoFieldCreateRequest(BaseModel):
    """创建字段请求体"""
    name: str = Field(..., min_length=1, max_length=128, description="字段显示名")
    type: FIELD_TYPES = Field(
        default="TEXT",
        description="字段类型：TEXT=文本, NUMBER=数字, SELECT=下拉, DATE=日期",
    )
    options: Optional[List[str]] = Field(
        None,
        description="type=SELECT 时的下拉选项列表",
    )
    sort_order: int = Field(0, ge=0, description="排序序号，数字越小越靠前")
    description: Optional[str] = Field(None, max_length=255, description="备注")

    def to_orm(self) -> "ExtraInfoField":
        """Request → ORM 工厂。"""
        from src.models.extra_info_field import ExtraInfoField

        return ExtraInfoField(
            name=self.name,
            type=self.type,
            options=self.options or [],
            sort_order=self.sort_order,
            is_active=True,
            description=self.description,
        )


class ExtraInfoFieldUpdateRequest(BaseModel):
    """修改字段请求体（所有字段可选）"""
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=128)
    type: Optional[FIELD_TYPES] = Field(None)
    options: Optional[List[str]] = Field(None)
    sort_order: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = Field(None)
    description: Optional[str] = Field(None, max_length=255)

    def apply_to(self, field) -> bool:
        """把非空字段写回 ORM 对象。返回是否有字段被实际修改。"""
        modified = False
        if self.name is not None:
            field.name = self.name
            modified = True
        if self.type is not None:
            field.type = self.type
            modified = True
        if self.options is not None:
            field.options = self.options
            modified = True
        if self.sort_order is not None:
            field.sort_order = self.sort_order
            modified = True
        if self.is_active is not None:
            field.is_active = self.is_active
            modified = True
        if self.description is not None:
            field.description = self.description
            modified = True
        return modified

    def is_empty(self) -> bool:
        """检测"没有任何字段被传入"。"""
        return (
            self.name is None
            and self.type is None
            and self.options is None
            and self.sort_order is None
            and self.is_active is None
            and self.description is None
        )


class ExtraInfoFieldListQueryRequest(BaseModel):
    """字段列表查询参数"""
    model_config = ConfigDict(populate_by_name=True)

    includeInactive: bool = Field(default=False, description="是否包含已停用字段")


class ExtraInfoFieldPageQueryRequest(BaseModel):
    """字段分页查询参数"""
    model_config = ConfigDict(populate_by_name=True)

    includeInactive: bool = Field(default=False)
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=100, ge=1, le=1000)


# ========== 响应 VO ==========

class ExtraInfoFieldVO(BaseModel):
    """字段视图（基础字段）"""
    id: int
    name: str
    type: str
    options: List[str] = Field(default_factory=list)
    sortOrder: int
    isActive: bool
    description: Optional[str] = None

    @classmethod
    def from_orm_to_vo(cls, obj) -> "ExtraInfoFieldVO":
        return cls(
            id=obj.id,
            name=obj.name,
            type=obj.type,
            options=obj.options or [],
            sortOrder=obj.sort_order,
            isActive=obj.is_active,
            description=obj.description,
        )


class ExtraInfoFieldListVO(Page[ExtraInfoFieldVO]):
    """字段分页列表 VO"""
    pass


__all__ = [
    "FIELD_TYPES",
    "ExtraInfoFieldCreateRequest",
    "ExtraInfoFieldUpdateRequest",
    "ExtraInfoFieldListQueryRequest",
    "ExtraInfoFieldPageQueryRequest",
    "ExtraInfoFieldVO",
    "ExtraInfoFieldListVO",
]
