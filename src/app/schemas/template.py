"""Template / Rule / Attribute 模块 DTO / VO

架构约定（与 file 模块一致）：
- Request 负责"接收输入 + 校验 + 提供转换方法（to_orm / apply_to / to_conditions）"
- VO 只做"ORM → 序列化"的投影
    - 转换方法为 `from_orm_to_vo(obj)`（语义清晰，与 Page.from_list_to_page 对称）
- 列表场景使用 Page[T] / XXXListVO(Page[T]) 模式
- type 字段统一通过 AttributeTypeEnum 校验；Rule 与 Attribute 联动

字段语义（v4）：
- Rule.type / Attribute.type: CONDITION / TRANSFORM
  - CONDITION: value=""（分数下沉到 rule.score）
  - TRANSFORM: value=公式（含 input 变量）
- template 不带 type 字段（业务允许混用 CONDITION + TRANSFORM rule）

v5（action-style 统一接口）：
- Template：
  - POST /api/bonus-template/save    新建：template + ruleIds（全量替换绑定的 rule）
  - POST /api/bonus-template/update  编辑：template + ruleIds（全量 DIFF 重置 rule 绑定）
  - POST /api/bonus-template/delete  删除：仅 templateId
- Rule：
  - POST /api/rule/save    新建：rule + attributeIds（全量替换绑定的 attribute）
  - POST /api/rule/update  编辑：rule + attributeIds（全量 DIFF 重置 attribute 绑定）
  - POST /api/rule/delete  删除：仅 ruleId（拒绝被 template 绑定）
- 旧的 REST 路由（POST "" / PUT / DELETE /{id}/attributes 等）已被废弃，不再保留
"""
from decimal import Decimal
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field, ConfigDict, field_validator, condecimal

from src.app.schemas.page import Page
from src.models.template import AttributeType


# ============================================================
# 内部工具：枚举归一化
# ============================================================

def _normalize_type(v: Optional[str]) -> Optional[str]:
    """归一化 type 输入（不区分大小写）"""
    if v is None:
        return None
    v = v.strip().upper()
    if v not in ("CONDITION", "TRANSFORM"):
        raise ValueError(f"type 必须是 CONDITION / TRANSFORM，当前值: {v}")
    return v


def _format_decimal(v: Optional[Decimal]) -> Optional[str]:
    """Decimal → 字符串（避免 JSON 序列化失败）"""
    if v is None:
        return None
    return str(v)


# ============================================================
# Rule DTO / VO
# ============================================================

class RuleCreateRequest(BaseModel):
    """创建规则请求（v5 已废弃，保留旧 DTO 仅供 type-score 校验复用）

    实际业务改用 RuleSaveRequest（rule + attributeIds 复合提交）。
    本类只用于 Service.validate() 内部做 type-score 一致性检查。
    """

    type: str = Field(
        default=AttributeType.CONDITION.value,
        description="规则类型：CONDITION / TRANSFORM",
    )
    score: Optional[condecimal(ge=0, max_digits=5, decimal_places=2)] = Field(
        None, description="CONDITION 模式必填；TRANSFORM 模式必须 None",
    )
    name: str = Field(..., min_length=1, max_length=100, description="规则名")
    sortOrder: int = Field(0, ge=0, description="全局显示顺序")
    description: Optional[str] = Field(None, description="备注")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        return _normalize_type(v)  # type: ignore[return-value]


class RuleUpdateRequest(BaseModel):
    """修改规则请求（v5 已废弃，保留旧 DTO 仅供 type-score 校验复用）

    实际业务改用 RuleSaveUpdateRequest。
    本类只用于 Service.validate() 内部做 type-score 一致性检查。
    """

    model_config = ConfigDict(extra="forbid")

    type: Optional[str] = Field(None, description="新类型")
    score: Optional[condecimal(ge=0, max_digits=5, decimal_places=2)] = Field(
        None, description="新分数",
    )

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: Optional[str]) -> Optional[str]:
        return _normalize_type(v)


class RuleVO(BaseModel):
    """规则视图（含统计信息）"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    score: Optional[str] = None
    name: str
    sortOrder: int
    description: Optional[str] = None
    isActive: bool

    @classmethod
    def from_orm_to_vo(cls, obj) -> "RuleVO":
        return cls(
            id=obj.id,
            type=obj.type,
            score=_format_decimal(obj.score),
            name=obj.name,
            sortOrder=obj.sort_order,
            description=obj.description,
            isActive=obj.is_active,
        )


class RuleDetailVO(RuleVO):
    """规则详情（含绑定的 attribute 列表）"""

    attributes: List["AttributeVO"] = Field(
        default_factory=list,
        description="绑定的属性列表",
    )

    @classmethod
    def from_orm_to_vo(cls, obj, attributes: Optional[List["AttributeVO"]] = None) -> "RuleDetailVO":
        base = RuleVO.from_orm_to_vo(obj).model_dump()
        return cls(**base, attributes=attributes or [])


# ============================================================
# Attribute DTO / VO
# ============================================================

class AttributeCreateRequest(BaseModel):
    """创建属性请求"""

    name: str = Field(..., min_length=1, max_length=100, description="选项名 / 区间名")
    groupCode: str = Field(..., min_length=1, max_length=50, description="技术 key（前端 GROUP BY 用）")
    groupName: str = Field(..., min_length=1, max_length=100, description="显示名")
    type: str = Field(
        default=AttributeType.CONDITION.value,
        description="属性类型：CONDITION / TRANSFORM",
    )
    value: str = Field(default="", description="CONDITION: 空串；TRANSFORM: 公式字符串（含 input）")
    inputMin: Optional[condecimal(ge=0, max_digits=10, decimal_places=4)] = Field(
        None, description="TRANSFORM 半开半闭下限（null=无限制）",
    )
    inputMax: Optional[condecimal(ge=0, max_digits=10, decimal_places=4)] = Field(
        None, description="TRANSFORM 半开半闭上限（null=无限制）",
    )
    sortOrder: int = Field(0, ge=0)
    description: Optional[str] = Field(None)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        return _normalize_type(v)  # type: ignore[return-value]

    def to_orm(self) -> "Attribute":
        """构造 ORM 对象（service 校验通过后落库）"""
        from src.models.template import Attribute

        return Attribute(
            name=self.name,
            group_code=self.groupCode,
            group_name=self.groupName,
            type=self.type,
            value=self.value,
            input_min=self.inputMin,
            input_max=self.inputMax,
            sort_order=self.sortOrder,
            description=self.description,
            is_active=True,
        )


class AttributeUpdateRequest(BaseModel):
    """修改属性请求（所有字段可选）"""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    groupCode: Optional[str] = Field(None, min_length=1, max_length=50)
    groupName: Optional[str] = Field(None, min_length=1, max_length=100)
    type: Optional[str] = Field(None)
    value: Optional[str] = Field(None)
    inputMin: Optional[condecimal(ge=0, max_digits=10, decimal_places=4)] = Field(None)
    inputMax: Optional[condecimal(ge=0, max_digits=10, decimal_places=4)] = Field(None)
    sortOrder: Optional[int] = Field(None, ge=0)
    description: Optional[str] = Field(None)
    isActive: Optional[bool] = Field(None)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: Optional[str]) -> Optional[str]:
        return _normalize_type(v)

    def apply_to(self, attr) -> bool:
        """把非空字段写回 ORM。返回是否有字段被实际修改。"""
        modified = False
        if self.name is not None:
            attr.name = self.name
            modified = True
        if self.groupCode is not None:
            attr.group_code = self.groupCode
            modified = True
        if self.groupName is not None:
            attr.group_name = self.groupName
            modified = True
        if self.type is not None:
            attr.type = self.type
            modified = True
        if self.value is not None:
            attr.value = self.value
            modified = True
        if self.inputMin is not None:
            attr.input_min = self.inputMin
            modified = True
        if self.inputMax is not None:
            attr.input_max = self.inputMax
            modified = True
        if self.sortOrder is not None:
            attr.sort_order = self.sortOrder
            modified = True
        if self.description is not None:
            attr.description = self.description
            modified = True
        if self.isActive is not None:
            attr.is_active = self.isActive
            modified = True
        return modified


class AttributeVO(BaseModel):
    """属性视图"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    groupCode: str
    groupName: str
    type: str
    value: str
    inputMin: Optional[str] = None
    inputMax: Optional[str] = None
    sortOrder: int
    description: Optional[str] = None
    isActive: bool

    @classmethod
    def from_orm_to_vo(cls, obj) -> "AttributeVO":
        return cls(
            id=obj.id,
            name=obj.name,
            groupCode=obj.group_code,
            groupName=obj.group_name,
            type=obj.type,
            value=obj.value or "",
            inputMin=_format_decimal(obj.input_min),
            inputMax=_format_decimal(obj.input_max),
            sortOrder=obj.sort_order,
            description=obj.description,
            isActive=obj.is_active,
        )


class AttributeListVO(Page[AttributeVO]):
    """属性分页列表 VO（语义别名）"""

    pass


# ============================================================
# Template DTO / VO
# ============================================================

class TemplateCreateRequest(BaseModel):
    """创建模板请求"""

    name: str = Field(..., min_length=1, max_length=100, description="模板名")
    categoryId: int = Field(..., ge=1, description="绑定的分类 ID（叶子节点）")
    maxScore: condecimal(ge=0, max_digits=5, decimal_places=2) = Field(
        ..., description="本模板单次申请上限",
    )
    reviewCount: int = Field(1, ge=1, description="审核员人数")
    sortOrder: int = Field(0, ge=0, description="展示顺序")
    description: Optional[str] = Field(None, description="备注")

    def to_orm(self) -> "Template":
        """构造 ORM 对象（service 校验通过后落库）"""
        from src.models.template import Template

        return Template(
            name=self.name,
            category_id=self.categoryId,
            max_score=self.maxScore,
            review_count=self.reviewCount,
            sort_order=self.sortOrder,
            description=self.description,
            is_active=True,
        )


class TemplateUpdateRequest(BaseModel):
    """修改模板请求（所有字段可选）"""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    maxScore: Optional[condecimal(ge=0, max_digits=5, decimal_places=2)] = Field(None)
    reviewCount: Optional[int] = Field(None, ge=1)
    sortOrder: Optional[int] = Field(None, ge=0)
    description: Optional[str] = Field(None)
    isActive: Optional[bool] = Field(None)

    def apply_to(self, template) -> bool:
        """把非空字段写回 ORM。返回是否有字段被实际修改。"""
        modified = False
        if self.name is not None:
            template.name = self.name
            modified = True
        if self.maxScore is not None:
            template.max_score = self.maxScore
            modified = True
        if self.reviewCount is not None:
            template.review_count = self.reviewCount
            modified = True
        if self.sortOrder is not None:
            template.sort_order = self.sortOrder
            modified = True
        if self.description is not None:
            template.description = self.description
            modified = True
        if self.isActive is not None:
            template.is_active = self.isActive
            modified = True
        return modified


class TemplateVO(BaseModel):
    """模板基础视图"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    categoryId: int
    maxScore: str
    reviewCount: int
    sortOrder: int
    description: Optional[str] = None
    isActive: bool

    @classmethod
    def from_orm_to_vo(cls, obj) -> "TemplateVO":
        return cls(
            id=obj.id,
            name=obj.name,
            categoryId=obj.category_id,
            maxScore=_format_decimal(obj.max_score),
            reviewCount=obj.review_count,
            sortOrder=obj.sort_order,
            description=obj.description,
            isActive=obj.is_active,
        )


class TemplateDetailVO(TemplateVO):
    """模板详情（含完整规则树）"""

    rules: List[RuleDetailVO] = Field(
        default_factory=list,
        description="模板绑定的规则列表（含 attribute 详情）",
    )
    isMixedType: bool = Field(
        default=False,
        description="是否混用了 CONDITION + TRANSFORM rule（业务允许，仅软提示）",
    )

    @classmethod
    def from_orm_to_vo(
        cls,
        obj,
        rules: Optional[List[RuleDetailVO]] = None,
        is_mixed_type: bool = False,
    ) -> "TemplateDetailVO":
        base = TemplateVO.from_orm_to_vo(obj).model_dump()
        return cls(**base, rules=rules or [], isMixedType=is_mixed_type)


class TemplateListQueryRequest(BaseModel):
    """模板列表查询请求"""

    model_config = ConfigDict(populate_by_name=True)

    categoryId: Optional[int] = Field(default=None, description="按分类 ID 过滤")
    isActive: Optional[bool] = Field(default=None, description="是否启用")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)

    def to_conditions(self) -> list:
        """翻译为 SQLAlchemy where 条件列表（与 file.FileQueryRequest 一致）"""
        from src.models.template import Template

        conds: list = []
        if self.categoryId is not None:
            conds.append(Template.category_id == self.categoryId)
        if self.isActive is not None:
            conds.append(Template.is_active == self.isActive)
        return conds


class TemplateListVO(Page[TemplateVO]):
    """模板分页列表 VO（语义别名）"""

    pass


class TemplateCategoryListQueryRequest(BaseModel):
    """按分类查询模板（学生端）—— 前端从 /api/template-category/leaf 拿到叶子分类后再选 template"""

    model_config = ConfigDict(populate_by_name=True)

    categoryId: int = Field(..., description="分类 ID", ge=1)


# ============================================================
# 关联操作 DTO
# ============================================================

class TemplateBindRuleRequest(BaseModel):
    """template ↔ rule 绑定请求"""

    ruleId: int = Field(..., ge=1, description="rule ID")


class TemplateBindRuleResultVO(BaseModel):
    """template ↔ rule 绑定返回（v4 含软提示）"""

    bound: bool
    isMixedType: bool = Field(
        description="是否混用了 CONDITION + TRANSFORM rule（业务合法，软提示）",
    )


class RuleBindAttributeRequest(BaseModel):
    """rule ↔ attribute 绑定请求"""

    attributeId: int = Field(..., ge=1, description="attribute ID")


# ============================================================
# v5 action-style 统一接口 DTO
# ============================================================
#
# 设计目的：
# - 新建/编辑 template 时，前端把"template 字段 + 最终绑定的 ruleIds 列表"打包成一个请求
# - 后端在一个事务里完成 template upsert + rule 全量替换（DIFF 语义）
# - 避免前端"先创建 template 再循环 bind rule"的多事务脏窗口
#
# 旧 REST 接口（POST "" / PUT / DELETE /{id}/rules 等）保留兼容旧调用方


class TemplatePayload(BaseModel):
    """template 字段子结构（被 Save / Update 共用）

    设计决策：把 template 字段做成独立子结构 + nested，方便前端组装 payload
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=100, description="模板名")
    categoryId: int = Field(..., ge=1, description="绑定的分类 ID（叶子节点）")
    maxScore: condecimal(gt=0, max_digits=5, decimal_places=2) = Field(
        ..., description="本模板单次申请上限（>0）",
    )
    reviewCount: int = Field(1, ge=1, description="审核员人数")
    sortOrder: int = Field(0, ge=0, description="展示顺序")
    description: Optional[str] = Field(None, description="备注")
    isActive: bool = Field(True, description="是否启用（仅 Update 实际生效；Save 时强制为 True）")

    def to_orm(self) -> "Template":
        """构造 ORM 对象（service 校验通过后落库）"""
        from src.models.template import Template

        return Template(
            name=self.name,
            category_id=self.categoryId,
            max_score=self.maxScore,
            review_count=self.reviewCount,
            sort_order=self.sortOrder,
            description=self.description,
            is_active=True,  # 新建场景强制启用
        )

    def apply_to(self, template) -> bool:
        """把字段写回 ORM（覆盖式；返回是否有字段被实际修改）"""
        modified = False
        if template.name != self.name:
            template.name = self.name
            modified = True
        if template.category_id != self.categoryId:
            template.category_id = self.categoryId
            modified = True
        if template.max_score != self.maxScore:
            template.max_score = self.maxScore
            modified = True
        if template.review_count != self.reviewCount:
            template.review_count = self.reviewCount
            modified = True
        if template.sort_order != self.sortOrder:
            template.sort_order = self.sortOrder
            modified = True
        if (template.description or None) != (self.description or None):
            template.description = self.description
            modified = True
        if template.is_active != self.isActive:
            template.is_active = self.isActive
            modified = True
        return modified


class TemplateSaveRequest(BaseModel):
    """新建 template + 一次性绑 rule（POST /save）

    - ruleIds 为空数组 → 创建后无任何绑 rule
    - ruleIds 全量生效（DIFF 语义：旧绑定全清，新绑定按此列表）
    """

    template: TemplatePayload
    ruleIds: List[int] = Field(default_factory=list, description="绑定的 rule id 列表（全量替换）")


class TemplateDeleteRequest(BaseModel):
    """删除 template（POST /delete）

    - 仅需 templateId
    - service 校验：是否存在未关闭的 application → ConflictError
    """

    templateId: int = Field(..., ge=1, description="被删除的 template ID")


class TemplateSaveUpdateRequest(BaseModel):
    """编辑 template + 重置 rule 绑定（POST /update）

    - templateId 必填；service 校验存在性
    - ruleIds 为空数组 → 解绑全部 rule
    - ruleIds 全量生效（DIFF 语义）

    命名说明：避免与旧的 PUT 路由用的 TemplateUpdateRequest 同名冲突，
    故加 Save 前缀表示"复合保存（template 字段 + rule 全量）"。
    """

    templateId: int = Field(..., ge=1, description="被编辑的 template ID")
    template: TemplatePayload
    ruleIds: List[int] = Field(default_factory=list, description="最终绑定的 rule id 列表（全量替换）")


class TemplateSaveResponse(BaseModel):
    """save / update 统一返回

    包含：
    - 新建/编辑后的 template 完整 VO（含 rules）
    - 当前绑定的 rule_id 列表（按 rule.sort_order 排序）
    - isMixedType 软提示（业务合法）
    """

    templateId: int
    template: TemplateDetailVO
    boundRuleIds: List[int]
    isMixedType: bool


# ============================================================
# v5 rule action-style DTO
# ============================================================

class RulePayload(BaseModel):
    """rule 字段子结构（save / update 共用，与 TemplatePayload 对称）"""

    model_config = ConfigDict(populate_by_name=True)

    type: str = Field(..., description="CONDITION / TRANSFORM")
    score: Optional[condecimal(ge=0, max_digits=5, decimal_places=2)] = Field(
        None, description="CONDITION 必填；TRANSFORM 必须 None",
    )
    name: str = Field(..., min_length=1, max_length=100)
    sortOrder: int = Field(0, ge=0)
    description: Optional[str] = Field(None)
    isActive: bool = Field(True, description="新建强制 True；编辑时实际生效")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        return _normalize_type(v)  # type: ignore[return-value]

    def to_orm(self) -> "Rule":
        """构造 ORM 对象（新建用）"""
        from src.models.template import Rule

        return Rule(
            type=self.type,
            score=self.score,
            name=self.name,
            sort_order=self.sortOrder,
            description=self.description,
            is_active=True,  # 新建强制启用
        )

    def apply_to(self, rule) -> bool:
        """覆盖式写回 ORM；返回是否有字段被实际修改。"""
        modified = False
        if rule.type != self.type:
            rule.type = self.type
            modified = True
        if (rule.score or None) != (self.score or None):
            rule.score = self.score
            modified = True
        if rule.name != self.name:
            rule.name = self.name
            modified = True
        if rule.sort_order != self.sortOrder:
            rule.sort_order = self.sortOrder
            modified = True
        if (rule.description or None) != (self.description or None):
            rule.description = self.description
            modified = True
        if rule.is_active != self.isActive:
            rule.is_active = self.isActive
            modified = True
        return modified


class RuleSaveRequest(BaseModel):
    """新建 rule + 一次性绑 attribute（POST /api/rule/save）"""

    rule: RulePayload
    attributeIds: List[int] = Field(
        default_factory=list,
        description="绑定的 attribute id 列表（全量替换）",
    )


class RuleSaveUpdateRequest(BaseModel):
    """编辑 rule + 重置 attribute 绑定（POST /api/rule/update）"""

    ruleId: int = Field(..., ge=1, description="被编辑的 rule ID")
    rule: RulePayload
    attributeIds: List[int] = Field(
        default_factory=list,
        description="最终绑定的 attribute id 列表（全量替换）",
    )


class RuleDeleteRequest(BaseModel):
    """删除 rule（POST /api/rule/delete）"""

    ruleId: int = Field(..., ge=1, description="被删除的 rule ID")


class RuleSaveResponse(BaseModel):
    """save / update 统一返回（与 TemplateSaveResponse 对称）"""

    ruleId: int
    rule: RuleDetailVO
    boundAttributeIds: List[int]


__all__ = [
    # Rule
    "RuleCreateRequest",
    "RuleUpdateRequest",
    "RuleVO",
    "RuleDetailVO",
    # Attribute
    "AttributeCreateRequest",
    "AttributeUpdateRequest",
    "AttributeVO",
    "AttributeListVO",
    # Template
    "TemplateCreateRequest",
    "TemplateUpdateRequest",
    "TemplateVO",
    "TemplateDetailVO",
    "TemplateListQueryRequest",
    "TemplateListVO",
    "TemplateCategoryListQueryRequest",
    # 关联操作（废弃：保留仅供类型提示）
    "TemplateBindRuleRequest",
    "TemplateBindRuleResultVO",
    "RuleBindAttributeRequest",
    # v5 action-style - Template
    "TemplatePayload",
    "TemplateSaveRequest",
    "TemplateSaveUpdateRequest",
    "TemplateDeleteRequest",
    "TemplateSaveResponse",
    # v5 action-style - Rule
    "RulePayload",
    "RuleSaveRequest",
    "RuleSaveUpdateRequest",
    "RuleDeleteRequest",
    "RuleSaveResponse",
]