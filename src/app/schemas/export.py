"""学生数据导出 DTO（v8.1 - 通用列树 + 行展开自动推断 + 不持久化）

设计要点：
- 列结构：树形 ExportColumnNode，支持任意深度嵌套
- 行展开：后端自动推断（category 子列含 application_* → 按 application 展开，否则占 1 行）
- source 白名单：user_basic / user_extra / application_* / category
- 层级约束：application_* 必须挂 category 下（"application 不能离开 template"）
- 不持久化：ExportUsersRequest 直接携带列树，无需 export_template 表

详见 docs/docs-backend/导出表格/export-后端实现方案.md
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ========== 原子字段来源白名单 ==========

# 学生维度（每学生一个值）
USER_BASIC = "user_basic"
USER_EXTRA = "user_extra"

# application 维度（每个 application 一个值，行展开时多列/多行）
APPLICATION_APPLY = "application_apply"     # app.apply_score
APPLICATION_GAIN = "application_gain"       # app.gain_score
APPLICATION_ATTR = "application_attr"       # app.rule_info[rule_name] → attribute.name
APPLICATION_STATUS = "application_status"   # app.status
APPLICATION_REMARK = "application_remark"   # app.remark
APPLICATION_FIELD = "application_field"     # app.<任意字段>（白名单）

# 容器节点（不直接出值，承载子列）
CATEGORY = "category"

ColumnSource = Literal[
    "user_basic",
    "user_extra",
    "application_apply",
    "application_gain",
    "application_attr",
    "application_status",
    "application_remark",
    "application_field",
    "category",
]

# 必须挂 category 节点下的 source（"application 不能离开 template"）
CONSTRAINED_SOURCES = frozenset({
    APPLICATION_APPLY,
    APPLICATION_GAIN,
    APPLICATION_ATTR,
    APPLICATION_STATUS,
    APPLICATION_REMARK,
    APPLICATION_FIELD,
})


# ========== 列节点（树形） ==========

class ExportColumnNode(BaseModel):
    """导出列树的一个节点（树形，支持任意深度）

    字段语义：
    - id                前端生成 nanoid，保证树内唯一
    - label             显示名（用户可改）
    - originalLabel     原始名（重置用）
    - source            原子来源（白名单）
    - level             0=顶级, 1=子, 2=孙...（前端自填，后端也接受）
    - sortOrder         同级排序（前端维护，后端只在排序冲突时 fallback）
    - parentId          父节点 id（顶级为 null）
    - categoryId        仅 category 列（template_category.id）
    - ruleName          仅 application_attr 列（rule.name → app.rule_info[rule_name]）
    - basicField        仅 user_basic 列（User 表白名单字段名）
    - fieldPath         仅 user_extra 列（extra_info_field.name）
    - cellTransform     仅 user_basic 列（'grade' → 1 → "大一"）
    - children          子节点（递归）
    """
    id: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=100)
    originalLabel: str = Field(..., min_length=1, max_length=100)
    source: ColumnSource
    level: int = Field(..., ge=0, le=10)
    sortOrder: int = Field(default=0, ge=0)
    parentId: Optional[str] = None

    # === 仅 category 列 ===
    categoryId: Optional[int] = Field(default=None, ge=1)

    # === 仅 application_attr 列 ===
    ruleName: Optional[str] = Field(default=None, max_length=100)

    # === 仅 application_field 列（Application ORM 白名单字段名） ===
    appField: Optional[str] = Field(default=None, max_length=50)

    # === 仅 user_basic 列 ===
    basicField: Optional[str] = Field(default=None, max_length=50)

    # === 仅 user_extra 列 ===
    fieldPath: Optional[str] = Field(default=None, max_length=128)

    # === 通用 ===
    cellTransform: Optional[str] = Field(default=None, max_length=20)

    # === 子节点（递归） ===
    children: List["ExportColumnNode"] = Field(default_factory=list)


# 递归模型需要 model_rebuild
ExportColumnNode.model_rebuild()


# ========== 用户基础字段白名单（user_basic 列能引用的字段名） ==========

USER_BASIC_FIELDS = frozenset({
    "username",
    "fullName",
    "studentId",          # 优先 users.student_id，fallback 到 extract_student_id(username)
    "department",
    "major",
    "grade",
    "enrollmentYear",
    "graduationYear",
    "phone",
    "gender",
    "idCardNumber",
    "lastLoginAt",
})


# ========== application 字段白名单（application_field 列能引用的字段名） ==========
# 与 Application ORM 模型字段一一对应（src/models/application.py）
APPLICATION_FIELDS = frozenset({
    "id",
    "user_id",
    "template_id",
    "template_name",
    "category_id",
    "apply_score",
    "gain_score",
    "status",
    "review_count",
    "approved_count",
    "rejected_count",
    "created_at",
    "updated_at",
    "rule_info",
})


# ========== 学生范围过滤条件 ==========

class ExportUserFilters(BaseModel):
    """导出学生范围过滤条件（与 UserQueryRequest 大致一致，admin 用）"""
    username: Optional[str] = Field(default=None, max_length=64)
    fullName: Optional[str] = Field(default=None, max_length=100)
    major: Optional[str] = Field(default=None, max_length=100)
    department: Optional[str] = Field(default=None, max_length=100)
    grade: Optional[int] = Field(default=None, ge=1, le=10)
    enrollmentYear: Optional[int] = Field(default=None, ge=2000, le=2100)
    graduationYear: Optional[int] = Field(default=None, ge=2000, le=2100)


# ========== 导出请求 ==========

class ExportUsersRequest(BaseModel):
    """学生数据导出请求（POST /api/user/admin/export）

    v8.1 关键：不再有 templateId / saveAsTemplate，列树直接由前端传入。
    """
    fileName: str = Field(
        default="students",
        min_length=1,
        max_length=64,
        description="导出文件名（不含扩展名，后端加 .xlsx）",
    )

    # 列树
    columns: List[ExportColumnNode] = Field(..., min_length=1, max_length=500)

    # 学生范围
    filters: ExportUserFilters = Field(default_factory=ExportUserFilters)
    studentIds: Optional[List[int]] = Field(default=None, max_length=5000)
    excludedIds: Optional[List[int]] = Field(default=None, max_length=5000)

    # 每个 category 最多展开多少 application（默认 5，防 Excel 列爆炸）
    maxApplicationsPerCategory: int = Field(default=5, ge=1, le=50)


__all__ = [
    # 列源常量
    "USER_BASIC",
    "USER_EXTRA",
    "APPLICATION_APPLY",
    "APPLICATION_GAIN",
    "APPLICATION_ATTR",
    "APPLICATION_STATUS",
    "APPLICATION_REMARK",
    "CATEGORY",
    "ColumnSource",
    "CONSTRAINED_SOURCES",
    # 列树
    "ExportColumnNode",
    # 用户基础字段白名单
    "USER_BASIC_FIELDS",
    # 请求体
    "ExportUserFilters",
    "ExportUsersRequest",
]
