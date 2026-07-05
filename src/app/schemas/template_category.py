"""模板分类 DTO / VO（Layer 1）

架构约定（与 file 模块一致）：
- Request 负责"接收输入 + 校验 + 提供转换方法（to_orm / apply_to）"
- VO     ：只做 ORM → 序列化投影，集中由 `from_orm_to_vo` 完成
- 列表场景使用 Page[T] / XXXListVO(Page[T]) 模式

字段语义（v2）：
- isBindTemplate: TRUE=该节点已绑定 template（不可再加子，不可再绑）
                FALSE=未绑 template（可加子，可绑 template）
- parentId 为 None → 创建根节点；非 None → 创建子节点

注意：本模块不保留嵌套树 VO（route 用临时 dict 即可），
前端 /tree 由 /list 走 Page 平铺，按 parentId 自行组树。
"""
from decimal import Decimal
from typing import Optional, List

from pydantic import BaseModel, Field, ConfigDict, condecimal

from src.app.schemas.page import Page


# ========== 请求 DTO ==========

class TemplateCategoryCreateRequest(BaseModel):
    """创建分类请求体

    - parentId=None → 根节点
    - parentId=int  → 子节点（service 内部按 parent 校验）
    """

    parentId: Optional[int] = Field(
        None, description="父分类 ID，null=创建根节点"
    )
    name: str = Field(..., min_length=1, max_length=100, description="分类名称")
    maxScore: condecimal(ge=0, max_digits=5, decimal_places=2) = Field(
        ..., description="本级分数上限，不允许为 null"
    )
    sortOrder: int = Field(0, ge=0, description="同级展示顺序")
    description: Optional[str] = Field(None, max_length=255, description="备注")

    def to_orm(self) -> "TemplateCategory":
        """Request → ORM 工厂：service 直接落库前一行调用即可。

        注：is_bind_template=FALSE 是新建默认；parent_id 直接取本 DTO 字段。
        """
        from src.models.template_category import TemplateCategory

        return TemplateCategory(
            name=self.name,
            parent_id=self.parentId,
            max_score=self.maxScore,
            is_bind_template=False,
            sort_order=self.sortOrder,
            is_active=True,
            description=self.description,
        )


class TemplateCategoryUpdateRequest(BaseModel):
    """修改分类请求体（所有字段可选）

    不允许修改 parentId / isBindTemplate / id（service 端校验）。
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=100, description="新名称")
    maxScore: Optional[condecimal(ge=0, max_digits=5, decimal_places=2)] = Field(
        None, description="新分数上限"
    )
    sortOrder: Optional[int] = Field(None, ge=0, description="新展示顺序")
    isActive: Optional[bool] = Field(None, description="启用 / 停用")
    description: Optional[str] = Field(None, max_length=255, description="新备注")

    def apply_to(self, category) -> bool:
        """把非空字段写回 ORM 对象。返回是否有字段被实际修改。

        service 看到 False 时直接跳过 commit，避免无意义事务。
        """
        modified = False
        if self.name is not None:
            category.name = self.name
            modified = True
        if self.maxScore is not None:
            category.max_score = self.maxScore
            modified = True
        if self.sortOrder is not None:
            category.sort_order = self.sortOrder
            modified = True
        if self.isActive is not None:
            category.is_active = self.isActive
            modified = True
        if self.description is not None:
            category.description = self.description
            modified = True
        return modified

    def is_empty(self) -> bool:
        """检测"没有任何字段被传入"——保留以便 service / route 提前判断。"""
        return (
            self.name is None
            and self.maxScore is None
            and self.sortOrder is None
            and self.isActive is None
            and self.description is None
        )


class TemplateCategoryListQueryRequest(BaseModel):
    """分类列表查询参数（GET /tree 兼容用）"""

    model_config = ConfigDict(populate_by_name=True)

    includeInactive: bool = Field(default=False, description="是否包含已停用节点")


class TemplateCategoryPageQueryRequest(BaseModel):
    """分类平铺分页列表（GET /list 场景）。

    Page[T] 风格与 file.search_files 一致：pageNum + pageSize。
    前端可基于 list + parentId 自组树渲染。
    """

    model_config = ConfigDict(populate_by_name=True)

    includeInactive: bool = Field(default=False, description="是否包含已停用节点")
    pageNum: int = Field(default=1, ge=1, description="页码")
    pageSize: int = Field(default=1000, ge=1, le=1000, description="每页大小")


# ========== 响应 VO ==========

class TemplateCategoryVO(BaseModel):
    """分类节点视图（基础字段）。"""

    id: int
    name: str
    parentId: Optional[int]
    maxScore: str
    isBindTemplate: bool
    sortOrder: int
    isActive: bool
    description: Optional[str] = None

    @classmethod
    def from_orm_to_vo(cls, obj) -> "TemplateCategoryVO":
        """ORM → VO（maxScore 统一转字符串以避免 Decimal JSON 失败）"""
        return cls(
            id=obj.id,
            name=obj.name,
            parentId=obj.parent_id,
            maxScore=str(obj.max_score),
            isBindTemplate=obj.is_bind_template,
            sortOrder=obj.sort_order,
            isActive=obj.is_active,
            description=obj.description,
        )


class TemplateCategoryDetailVO(TemplateCategoryVO):
    """分类详情（含完整路径）"""

    path: List[dict] = Field(
        default_factory=list,
        description="从根到当前节点的路径 [{id, name}]",
    )

    @classmethod
    def from_orm_to_vo(cls, obj, path: List[dict]) -> "TemplateCategoryDetailVO":
        base = TemplateCategoryVO.from_orm_to_vo(obj).model_dump()
        return cls(**base, path=path)


class TemplateCategoryDeletePreviewVO(BaseModel):
    """删除预览（强提醒对话窗数据源）"""

    category: TemplateCategoryVO
    descendants: List[TemplateCategoryVO]
    totalDeletedCount: int
    activeApplicationCount: int
    templateCount: int

    @classmethod
    def from_service_payload(cls, payload: dict) -> "TemplateCategoryDeletePreviewVO":
        return cls(
            category=TemplateCategoryVO.from_orm_to_vo(payload["category"]),
            descendants=[
                TemplateCategoryVO.from_orm_to_vo(d) for d in payload["descendants"]
            ],
            totalDeletedCount=payload["totalDeletedCount"],
            activeApplicationCount=payload["activeApplicationCount"],
            templateCount=payload["templateCount"],
        )


class TemplateCategoryListVO(Page[TemplateCategoryVO]):
    """分类平铺分页列表 VO（Page[TemplateCategoryVO] 的语义别名）。

    GET /list 返回此 VO，前端用 resp.data.list 做按 parentId 组树。
    """

    pass


__all__ = [
    "TemplateCategoryCreateRequest",
    "TemplateCategoryUpdateRequest",
    "TemplateCategoryListQueryRequest",
    "TemplateCategoryPageQueryRequest",
    "TemplateCategoryVO",
    "TemplateCategoryDetailVO",
    "TemplateCategoryDeletePreviewVO",
    "TemplateCategoryListVO",
]
