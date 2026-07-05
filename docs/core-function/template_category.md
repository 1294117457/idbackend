CREATE TABLE template_category (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    parent_id       INTEGER REFERENCES template_category(id),
    max_score       DECIMAL(5,2),
    is_bind_template BOOLEAN NOT NULL DEFAULT FALSE,    -- TRUE=已绑 template（不可再加子，不可再绑）
    sort_order      INTEGER DEFAULT 0,
    is_active       BOOLEAN DEFAULT TRUE,
    description     VARCHAR(255),
    created_at      TIMESTAMP,
    updated_at      TIMESTAMP
);

这里还有一个疑问，比如可能我会限制加分类型的最大值100分，学业加分等三个加分分别60，20，20，
这样还需要区分总申请最大值和单条最大值吗，后续申请是不是可以直接和叶子节点分类的最大值比较就好了
然后只要保证子分类的最大值和不超过父分类就没问题，
  同时后续学生计算分时从score_data更新到score_info时，增加分数的校验，
  这样在application层一层直接的申请的分数最大值校验，
  以及计算分数时校验子分类之和不超过父分类
这样是不是就没问题，然后每个分类就只需要一个最大值，

---

# TemplateCategory 具体实现设计

> 本文档为 `template_category` 表的**具体实现设计文档**（不写代码），与 `四层职责设计.md` 中的概念层对齐。
> 代码实现尚未落盘，仅描述 ORM 模型、Service 接口、Router 接口、前端交互等设计蓝图。
>
> **v2 重大调整（2026-07-05）**：业务侧"叶子/中间"的二元语义改为"是否已绑 template"。
> 分类树改为 N-ary 树（一个父节点可有 N 个子节点）；`is_bind_template` 是唯一状态机托管字段。

---

## 一、最终表结构（在草案基础上迭代）

> ⚠️ 2026-07-05 update：原 `is_leaf` 字段已被 `is_bind_template` 取代。
> 详见迁移 011：`migrations/011_rename_is_leaf_to_is_bind_template.py`

```sql
CREATE TABLE template_category (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    parent_id       INTEGER REFERENCES template_category(id),
    max_score       DECIMAL(5,2) NOT NULL CHECK (max_score >= 0),
    is_bind_template BOOLEAN NOT NULL DEFAULT FALSE,  -- 关键：TRUE=已绑 template
    sort_order      INTEGER NOT NULL DEFAULT 0,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    description     VARCHAR(255),
    created_at      TIMESTAMP,
    updated_at      TIMESTAMP
);

-- template 与 category_id 的 FK 改为 ON DELETE CASCADE，配合分类级联删除
ALTER TABLE score_templates
    DROP CONSTRAINT fk_score_templates_category_old,
    ADD CONSTRAINT fk_score_templates_category
        FOREIGN KEY (category_id) REFERENCES template_category(id)
        ON DELETE CASCADE;

-- 同级展示索引
CREATE INDEX idx_template_category_parent_sort
    ON template_category (parent_id, sort_order, id);
```

### 1.1 字段 `is_bind_template` 的语义

| 值 | 含义 | 是否可加子 | 是否可绑 template |
|---|---|---|---|
| **FALSE**（默认） | 节点未绑 template | ✓ | ✓ |
| **TRUE** | 节点已绑 template | ✗ | ✗ |

- 字段为 **NULL 不允许**（DB 层 `NOT NULL`，service 层默认值 = FALSE）
- service 层在 `create_child` 时校验父节点必须 `is_bind_template=FALSE`，否则拒绝加子
- service 层在 `bind_template` 时若已是 TRUE 则幂等返回
- service 层在 `unbind_template` 时把 `score_templates.category_id` 全部置 NULL，再翻 flag 回 FALSE

---

## 二、数据模型层（ORM）

新文件：`src/models/template_category.py`

```python
"""分类树模型"""
from sqlalchemy import String, Integer, ForeignKey, Text, Boolean, DECIMAL, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List

from .base import Base, TimestampMixin


class TemplateCategory(Base, TimestampMixin):
    """分类树表（template_category）"""
    __tablename__ = "template_category"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("template_category.id"), nullable=True
    )
    max_score: Mapped[float] = mapped_column(DECIMAL(5, 2), nullable=False)
    is_bind_template: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[Optional[str]] = mapped_column(String(255))

    # 关系（service 层组装树时使用）
    children: Mapped[List["TemplateCategory"]] = relationship(
        "TemplateCategory",
        back_populates="parent",
        cascade="all, delete-orphan",  # 内存层维护；DB 层由 ON DELETE CASCADE + 显式 service 删
        passive_deletes=True,
    )
    parent: Mapped[Optional["TemplateCategory"]] = relationship(
        "TemplateCategory", back_populates="children", remote_side="TemplateCategory.id"
    )
    templates: Mapped[List["ScoreTemplate"]] = relationship(
        "ScoreTemplate",
        back_populates="category",
        passive_deletes=True,  # DB 由 ON DELETE CASCADE 处理
    )

    __table_args__ = (
        CheckConstraint("max_score >= 0", name="ck_template_category_max_score_nonneg"),
    )
```

> `is_bind_template` 在 ORM 层显式声明，由 service 在 bind_template / unbind_template 时维护。

---

## 三、Service 层（业务编排）

新文件：`src/services/template_category_service.py`

### 3.1 错误定义（业务异常）

```python
class CategoryError(Exception): ...
class CategoryNotFound(CategoryError): ...
class CategoryHasActiveApplications(CategoryError):
    """删除时存在未关闭的 application，禁止删除"""
    def __init__(self, count: int):
        self.count = count
        super().__init__(f"该分类及其子分类下还有 {count} 条未关闭的申请，禁止删除")

class ParentAlreadyBound(CategoryError):
    """父节点 is_bind_template=TRUE（已绑 template），不可继续添加子分类"""
class CategoryNameDuplicate(CategoryError):
    """同级下 name 重复"""
```

### 3.2 公共读接口

```python
class TemplateCategoryService:

    @staticmethod
    async def get_tree(db: AsyncSession, *, include_inactive: bool = False) -> List[Dict]:
        """
        获取完整分类树，供管理端展示。
        - include_inactive=False（默认）：仅返回 is_active=TRUE 的节点
        - include_inactive=True：返回全部节点（仅管理后台"已停用"页面使用）
        返回结构：
        [
            {
                "id": 1, "name": "加分总计", "parentId": null, "maxScore": "100.00",
                "isLeaf": False, "sortOrder": 1, "isActive": True, "description": "...",
                "children": [ ... ],   # 递归嵌套
                "templateCount": 0,    # 仅叶子有意义；非叶永远为 0
            },
            ...
        ]
        排序：同级 ORDER BY sort_order ASC, id ASC（同 sort_order 按 id 稳定）
        """

    @staticmethod
    async def get_by_id(db: AsyncSession, category_id: int) -> Optional[TemplateCategory]: ...

    @staticmethod
    async def get_leaf_categories(
        db: AsyncSession,
        *,
        include_inactive: bool = False,
    ) -> List[TemplateCategory]:
        """
        获取所有 "is_bind_template=FALSE 且 is_active=TRUE" 的分类，供 TemplateService 在绑定时使用。
        这是 v2 调整后的语义（取代旧的"is_leaf=TRUE"）：未绑 template 即可绑。
        """

    @staticmethod
    async def get_category_path(
        db: AsyncSession, category_id: int
    ) -> List[TemplateCategory]:
        """获取从根到当前节点的完整路径，用于前端面包屑或权限校验"""
```

### 3.3 写接口

```python
class TemplateCategoryService:

    @staticmethod
    async def create_root(
        db: AsyncSession,
        *,
        name: str,
        max_score: Decimal,
        description: Optional[str] = None,
        sort_order: int = 0,
        created_by: int,
    ) -> TemplateCategory:
        """
        新增根节点（parent_id=NULL）：
        1. 校验 name 在顶级下唯一（否则抛 CategoryNameDuplicate）
        2. 写入（is_bind_template 默认 FALSE，新节点未绑 template）
        3. 单事务
        """

    @staticmethod
    async def create_child(
        db: AsyncSession,
        *,
        parent_id: int,
        name: str,
        max_score: Decimal,
        description: Optional[str] = None,
        sort_order: int = 0,
        created_by: int,
    ) -> TemplateCategory:
        """
        新增子分类（同一事务）—— N-ary 树，父可多个子：

        1. 加载父节点，不存在抛 CategoryNotFound
        2. 校验父节点 is_bind_template=FALSE（未绑 template），否则抛 ParentAlreadyBound
        3. 校验 name 在该父节点下唯一，抛 CategoryNameDuplicate
        4. 校验 max_score >= 0（DB CHECK 已兜底，service 层再做一次友好提示）
        5. 写入新分类（is_bind_template=FALSE，新节点默认未绑 template）
        6. 提交并 refresh 返回
        注：父节点的 is_bind_template 不需要翻转；父子数量无关。
        """

    @staticmethod
    async def update(
        db: AsyncSession,
        category_id: int,
        *,
        name: Optional[str] = None,
        max_score: Optional[Decimal] = None,
        sort_order: Optional[int] = None,
        is_active: Optional[bool] = None,
        description: Optional[str] = None,
        updated_by: int,
    ) -> TemplateCategory:
        """
        修改分类（仅允许修改这些字段）：
        - 不允许改 parent_id（要调整位置只能删旧建新）
        - 不允许改 is_bind_template（service 在 bind/unbind template 时维护）
        - 修改 max_score 后可选触发相关用户 score_data 聚合重算（见四层职责设计 Layer 4）
        - 修改 sort_order 不影响树结构，只影响 UI 顺序
        - is_active 由 True 改 False：立即从 get_tree 返回消失，历史数据不受影响
        - 修改 name 时校验同级唯一
        """

    @staticmethod
    async def delete(
        db: AsyncSession,
        category_id: int,
        *,
        operator_id: int,
    ) -> int:
        """
        删除分类节点（级联删除同一事务）：
        返回值：被删的节点总数（含级联后代）。

        执行流程（强一致，全部在一个事务里）：
        1. 加载分类，若不存在抛 CategoryNotFound
        2. 收集所有要删的分类 ID：本节点 + 所有后代（一次 SQL CTE）
        3. 预检：检查这些分类下是否存在未关闭的 application
           （status NOT IN ('PASSED','REJECTED') 或 status != 1），如有则抛 CategoryHasActiveApplications
        4. 删除节点（DB ON DELETE CASCADE 自动级联 template）；
           一次 DELETE FROM template_category WHERE id IN (...)
        5. 提交
        6. 不需要回滚 is_bind_template：因为被删节点的祖先可能也一并被删了
        注：template 不引用 attribute，所以 rule/attribute 不受影响
            不允许事务部分提交；任一步骤失败整体回滚
        """
```

### 3.4 不提供的接口
（与 v2 一致，无变化）

```python
# 明确不实现：
# - move(category_id, new_parent_id)
# - change_parent(category_id, new_parent_id)
# 原因：见四层职责设计.md "设计取舍 2.2"。
# 要调整分类位置只能"删除旧节点 + 新建子节点"。
```

### 3.5 v2 新增接口：template 绑定/解绑

```python
@staticmethod
async def bind_template(
    db: AsyncSession,
    category_id: int,
    *,
    template_id: int,
) -> TemplateCategory:
    """
    将 template 绑定到分类（service 层公开 API）：

    1. 加载分类，若不存在抛 CategoryNotFound
    2. 若已是 is_bind_template=TRUE，幂等返回
    3. 否则设置 is_bind_template=TRUE
    注：template.category_id 由 TemplateService 在创建/绑定时设置；
        本方法不重复设置 template.category_id。
    4. 提交并 refresh 返回
    """

@staticmethod
async def unbind_template(
    db: AsyncSession,
    category_id: int,
) -> TemplateCategory:
    """
    解绑：先把所有绑过来的 template.category_id 置 NULL；
        再把分类 is_bind_template 翻回 FALSE。
    用于：当最后一个 template 被解绑/删除时由 TemplateService 调用。
    """
```

---

## 四、Router 层（HTTP 接口）

新文件：`src/app/routes/template_category.py`

### 4.1 接口清单

| Method | Path | 权限码 | 用途 |
|---|---|---|---|
| GET | `/api/template-category/tree` | `template_category:read` | 获取分类树（管理端） |
| GET | `/api/template-category/leaf` | `template_category:read` | 获取所有叶子分类（绑定 template 用） |
| GET | `/api/template-category/{id}` | `template_category:read` | 获取详情（含 path 信息） |
| POST | `/api/template-category` | `template_category:create` | 创建分类（顶层或子分类） |
| PUT | `/api/template-category/{id}` | `template_category:update` | 修改分类 |
| DELETE | `/api/template-category/{id}` | `template_category:delete` | 删除分类（含级联） |

> 权限码由 `RbacService.get_path_permission` 在中间件层校验；本路由文件只做参数处理和调用 service。

### 4.2 Request / Response Schema（pydantic）

```python
from pydantic import BaseModel, Field, condecimal
from typing import Optional, List, Dict, Any


class TemplateCategoryCreate(BaseModel):
    """创建分类请求体"""
    parentId: Optional[int] = Field(
        None, description="父分类 ID，null=创建根节点"
    )
    name: str = Field(..., min_length=1, max_length=100)
    maxScore: condecimal(ge=0, max_digits=5, decimal_places=2) = Field(
        ..., description="本级分数上限，不允许为 null"
    )
    sortOrder: int = Field(0, ge=0)
    description: Optional[str] = Field(None, max_length=255)


class TemplateCategoryUpdate(BaseModel):
    """修改分类请求体（所有字段可选）"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    maxScore: Optional[condecimal(ge=0, max_digits=5, decimal_places=2)] = None
    sortOrder: Optional[int] = Field(None, ge=0)
    isActive: Optional[bool] = None
    description: Optional[str] = Field(None, max_length=255)
    # 不接受 parentId / isLeaf（service 层会忽略）

    class Config:
        extra = "forbid"   # 不允许传未知字段，type=parentId/isLeaf 一律拒绝
```

### 4.3 路由骨架（伪代码）

```python
"""分类管理路由"""
from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.deps import get_db
from src.app import response as R
from src.services.template_category_service import (
    TemplateCategoryService,
    CategoryNotFound,
    CategoryNameDuplicate,
    ParentAlreadyBound,           # ← 替代旧 ParentNotLeaf
    CategoryHasActiveApplications,
)

router = APIRouter(prefix="/api/template-category", tags=["分类管理"])


@router.get("/tree")
async def get_category_tree(
    includeInactive: bool = False,
    db: AsyncSession = Depends(get_db),
):
    tree = await TemplateCategoryService.get_tree(db, include_inactive=includeInactive)
    return R.success_resp(tree)


@router.get("/leaf")
async def get_leaf_categories(
    includeInactive: bool = False,
    db: AsyncSession = Depends(get_db),
):
    # v2 语义改为 is_bind_template=FALSE
    leaves = await TemplateCategoryService.get_leaf_categories(db, include_inactive=includeInactive)
    return R.success_resp([
        {
            "id": c.id, "parentId": c.parent_id, "name": c.name,
            "maxScore": str(c.max_score), "isActive": c.is_active,
            "isBindTemplate": c.is_bind_template,
        }
        for c in leaves
    ])


@router.post("")
async def create_category(data: TemplateCategoryCreate, db: AsyncSession = Depends(get_db)):
    try:
        category = await TemplateCategoryService.create_child(
            db,
            parent_id=data.parentId,
            name=data.name,
            max_score=data.maxScore,
            description=data.description,
            sort_order=data.sortOrder,
            created_by=get_user_id(),
        ) if data.parentId else await TemplateCategoryService.create_root(
            db,
            name=data.name,
            max_score=data.maxScore,
            description=data.description,
            sort_order=data.sortOrder,
            created_by=get_user_id(),
        )
    except (CategoryNameDuplicate, ParentAlreadyBound) as e:
        return R.bad_request_resp(str(e))
    return R.created_resp({
        "id": category.id, "name": category.name, "isBindTemplate": category.is_bind_template,
    })


@router.put("/{category_id}")
async def update_category(
    category_id: int = Path(..., ge=1),
    data: TemplateCategoryUpdate = ...,
    db: AsyncSession = Depends(get_db),
):
    try:
        category = await TemplateCategoryService.update(
            db, category_id,
            name=data.name, max_score=data.maxScore,
            sort_order=data.sortOrder, is_active=data.isActive,
            description=data.description,
            updated_by=get_user_id(),
        )
    except CategoryNotFound:
        return R.not_found_resp("分类不存在")
    except CategoryNameDuplicate as e:
        return R.bad_request_resp(str(e))
    if not category:
        return R.not_found_resp("分类不存在")
    return R.success_resp({
        "id": category.id, "name": category.name, "isBindTemplate": category.is_bind_template,
    })


@router.delete("/{category_id}")
async def delete_category(
    category_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
):
    try:
        deleted = await TemplateCategoryService.delete(db, category_id, operator_id=get_user_id())
    except CategoryNotFound:
        return R.not_found_resp("分类不存在")
    except CategoryHasActiveApplications as e:
        return R.bad_request_resp(
            f"该分类及其子分类下还有 {e.count} 条未关闭的申请，禁止删除",
            data={"activeApplicationCount": e.count},
        )
    return R.success_resp({
        "deletedCount": deleted,
        "msg": f"成功删除 {deleted} 个分类节点（含级联）",
    })
```

### 4.4 前置删除确认接口（可选）

> 为支持管理端在删除前展示"将要删除什么"的预览（强提醒对话窗的数据来源），增加一个预览接口：

```python
@router.get("/{category_id}/delete-preview")
async def get_delete_preview(category_id: int, db: AsyncSession = Depends(get_db)):
    """
    返回将级联删除的内容清单，供前端强提醒对话窗渲染（v2）：
    - 直接被删分类的 name / maxScore / isBindTemplate
    - 全部后代分类数量与名称列表（深度优先）
    - 全部绑定的 template 数量（用于前端权限校验提示）
    - 是否存在未关闭的 application（true 时前端直接禁用"确定"按钮）
    """
```

---

## 五、前端（管理端）交互设计

### 5.1 页面布局

```
┌─────────────────────────────────────────────────────────────────┐
│  分类管理（Layer 1）                                  [+新建根节点] │
├─────────────────────────────────────────────────────────────────┤
│  [正常] [已停用]                                                  │
│                                                                 │
│  ▶ 加分总计 (100.00)            可绑模板                [+子] [编辑] [删] │
│    ▶ 学业加分 (60.00)           可绑模板                [+子] [编辑] [删] │
│      ▶ 竞赛奖项 (20.00)         已绑模板 ⚠              [+子 ✗]   [编辑] [删] │
│      ▶ 学术论文 (10.00)         可绑模板                [+子] [编辑] [删] │
│    ▶ 专长加分 (20.00)           可绑模板                [+子] [编辑] [删] │
│    ▶ 劳动教育 (20.00)           可绑模板                [+子] [编辑] [删] │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 按钮可用性规则

| 节点状态 (`isBindTemplate`) | [+子] | [绑 Template] | [删] |
|---|---|---|---|
| FALSE，无 template | ✓ | ✓（如当前在模板编辑页） | ✓ |
| FALSE，有子节点 | ✓ | ✗（隐藏） | ✓（强提醒） |
| TRUE（已绑 template） | ✗ | ✓（已绑，可继续） | ✓（级联删 template，强提醒） |

> "已绑 template" 仍可继续绑新 template（不再是一对一）。解绑由 template 编辑页触发（service.unbind_template）。

### 5.3 删除强提醒对话窗

点击 [删] 弹出二次确认窗（不可 Esc 关掉，强制用户点确认或取消）：

```
┌─────────────────────────────────────────────────────────────┐
│  确认删除分类                                              ×│
├─────────────────────────────────────────────────────────────┤
│  ⚠ 你将删除以下 1 个分类、3 个后代节点、5 个绑定的模板：   │
│                                                             │
│   • 学业加分 (60.00) [已绑模板]                             │
│     └─ 竞赛奖项 (20.00) [可绑模板]                          │
│     └─ 学术论文 (10.00) [可绑模板]                          │
│                                                             │
│  ⚠ 此操作不可恢复！历史已通过的申请不受影响。               │
│  ⚠ 该分类下还有 0 条未关闭的申请。                          │
│                                                             │
│  请输入分类名称"学业加分"以确认：  ┌─────────────────┐    │
│                                     │                 │    │
│                                     └─────────────────┘    │
│                                                             │
│            [取消]                       [确认删除]          │
└─────────────────────────────────────────────────────────────┘
```

对话窗内容：
1. **分类树预览**：用 5.4 接口返回的数据渲染（缩进树状）
2. **未关闭申请数提示**：从 `delete-preview` 接口 `activeApplicationCount` 字段读
3. **输入分类名验证**：用户必须输入完全一致的 name 才能激活"确认删除"按钮（防误操作）
4. **二次点击按钮**：按钮文案"确认删除"而非"删除"，且点击后立刻 disable 防止双击重复请求

### 5.4 关键交互列表

| 操作 | API | 用户交互细节 |
|---|---|---|
| 新建根节点 | `POST /api/template-category` | 对话窗：name + maxScore + description + sortOrder，sortOrder 默认 0 |
| 新建子节点 | `POST /api/template-category` | 同上，parentId 由调用方预填当前节点 id；后端会校验父 is_bind_template=FALSE |
| 编辑节点 | `PUT /api/template-category/{id}` | 仅可改 name/maxScore/sortOrder/isActive/description，**不允许改 parent / isBindTemplate** |
| 删除节点 | `GET .../delete-preview` → `DELETE .../{id}` | 必须看到 5.3 强提醒对话窗，输入分类名才可点 |
| 调整顺序 | `PUT /api/template-category/{id}` | 直接传 sortOrder，按手动指定；未指定视为排同级末尾 |
| 启/停用 | `PUT .../{id}` | 仅传 isActive；停用后立即从主树消失，进入"已停用"页 |
| 绑 template | `TemplateService.create` 内调用 `bind_template` | service 端自动翻 flag |
| 解绑 template | `TemplateService.delete` 内调用 `unbind_template` | service 端自动翻 flag |

---

## 六、与现有 Layer 2（TemplateService）的衔接

`TemplateService.create` 的分类校验改为：

```python
category = await db.get(TemplateCategory, category_id)
if not category:
    raise CategoryNotFound(...)
# v2: 不再限制"是否叶子"，改为校验"是否已绑 template"
# 当前 store 端：未绑 template 即可绑；第一版允许重复绑第二版可加查重
# 不校验 max_score 与 template.max_score 的关系——template 内部独立封顶

# 创建成功后调用 bind_template 翻转 flag
await TemplateCategoryService.bind_template(db, category_id, template_id=template.id)
```

`TemplateService.get_by_category` 与分类树组合使用时，前端先调 `get_tree` 拿到全树，再按节点 id 拼 template 列表；或调 `get_with_rules(category_id)` 单独拉取。

### 6.1 v2 新增解绑回调

```python
# TemplateService.delete template 时：
template = await db.get(ScoreTemplate, template_id)
category_id = template.category_id
await db.delete(template)
if category_id is not None:
    # 检查该分类下是否还有其他 template
    remaining = await db.execute(
        select(func.count()).select_from(ScoreTemplate).where(
            ScoreTemplate.category_id == category_id
        )
    )
    if remaining.scalar_one() == 0:
        await TemplateCategoryService.unbind_template(db, category_id)
```

---

## 七、Alembic 迁移顺序

1. 新建 `template_category` 表（含 `is_bind_template` 字段、CHECK 约束）
2. 改造 `template.category_id` FK 为 `ON DELETE CASCADE`
3. 改造 `score_templates.template_type / score_type` 列数据 → 用 `category_id` 替换
4. 老数据迁移：
   - `FieldConfig` (score_type=SCORE) → `template_category` 根节点（parent_id=NULL）
   - `FieldSubcategory` → `template_category` 子节点（parent_id=FieldConfig.id）
   - 删除 `FieldConfig` / `FieldSubcategory`（如四层职责设计"六、与现有代码的迁移关系"所述）

---

## 八、典型场景端到端流程

### 场景 1：管理员新建两级分类

```
1. 管理员新增根节点"加分总计" maxScore=100
   → service: parent_id=NULL → is_bind_template=FALSE（默认）
2. 管理员在"加分总计"下新增"学业加分" maxScore=60
   → service: 父 is_bind_template=FALSE 校验通过；创建"学业加分" is_bind_template=FALSE
   → 父"加分总计" is_bind_template 保持 FALSE（与子节点数量无关）
3. 管理员在"学业加分"下新增"竞赛奖项" maxScore=20
   → service: 父 is_bind_template=FALSE 校验通过；创建"竞赛奖项" is_bind_template=FALSE
   → 父"学业加分" is_bind_template 保持 FALSE
```

### 场景 1b：admin 给"竞赛奖项"绑 template

```
4. 在 template 管理界面，给"竞赛奖项"绑某个 score_template
   → service: 校验"竞赛奖项" is_bind_template=FALSE（通过），设置 TRUE
   → 此时若再尝试给"竞赛奖项"加子："父节点已绑定 template" 拒绝
   → 此时若删 template：service.unbind_template 自动回收
```

### 场景 2：删除中间节点及其全部后代

```
管理员点击"学业加分"[删] → 前端调 /delete-preview
   → 返回：1 个待删分类 + 1 个后代 + 0 个 template + 0 条未关闭申请
   → 弹出强提醒对话窗，输入"学业加分"后才能点确定
   → 调 DELETE /api/template-category/{学业加分 id}
   → service 在一个事务内：
     a. 删"学业加分"和"竞赛奖项"（两条 DELETE FROM template_category WHERE id IN (...)）
     b. template.category_id 上 ON DELETE CASCADE 自动级联（若有）
     c. 检查"加分总计"是否还有其他子节点（无关）
     d. template 在 score_templates.category_id 上由 ON DELETE CASCADE 自动级联删除
   → 返回 deletedCount=2
```

### 场景 3：分类下有未关闭申请，禁止删除

```
管理员点击"学业加分"[删] → 前端调 /delete-preview
   → 返回 activeApplicationCount=2（非零）
   → 前端直接禁用"确认删除"按钮 + 显示橙色提示
     "存在 2 条未关闭申请，请联系管理员处理后再删除"
   → 关闭按钮，无法继续操作（保守策略）
```

### 场景 4：调位置（不支持 move，只能删旧建新）

```
原结构：
  加分总计
    ├─ 学业加分
    └─ 体育加分     ← 想移到"学业加分"下

管理员想调整 → 操作：
  1. 删除"体育加分"（若有 template，先删 template；前端强提醒对话窗）
  2. 在"学业加分"下新建"体育加分"（重建）
  3. 重新绑定原有 template
```

application 历史不受影响：历史 application 已快照 `template_name / template_id / category_id / category_path` 等字段，重建不破坏历史展示。

---

## 九、设计取舍与未来扩展

| 主题 | 当前决策 | 未来可扩展 |
|---|---|---|
| `is_bind_template` | ORM 字段；service 在 bind/unbind template 时维护 | 无需变化 |
| N-ary 树 | 父可有 N 个子（数量不限） | 无需变化 |
| 同一分类多 template | 允许（业务按需绑定） | 二期可加唯一性约束 |
| `max_score` | NOT NULL 且 >= 0 | 如需"中间节点不限"语义，可改可空，但 recalculate 算法需补特殊处理 |
| 删除级联 | 应用硬删除 + DB ON DELETE CASCADE | 如果误删成本变高，可改为 `is_active=FALSE` 软删除 + 物理删除只允许定时任务清理 |
| 移动节点 | 不提供 | 如真有必要可加，但 application 历史 schema 需加 `category_path` |
| 同名同级 | 拒绝 | 可改为允许同名，按 id 区分 |
| 删除预申请校验 | 只校验"未关闭申请" | 可扩展为"校验去年/历史 pass 申请数量"N 等 |
| 排序 | sort_order 单 int | 可加 parent_id + sort_order 二级排序，或拖拽重排时返回新 order 列表 |
