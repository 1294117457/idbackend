CREATE TABLE template_category (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    parent_id   INTEGER REFERENCES template_category(id),
    max_score   DECIMAL(5,2),
    sort_order  INTEGER DEFAULT 0,
    is_active   BOOLEAN DEFAULT TRUE,
    description VARCHAR(255),
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP
);

这里还有一个疑问，比如可能我会限制加分类型的最大值100分，学业加分等三个加分分别60，20，20，
这样还需要区分总申请最大值和单条最大值吗，后续申请是不是可以直接和叶子节点分类的最大值比较就好了
然后只要保证子分类的最大值和不超过父分类就没问题，
  同时后续学生计算分时从score_data更新到score_info时，增加分数的校验，
  这样在application层一层直接的申请的分数最大值校验，
  以及计算分数时校验子分类之和不超过父分类
这样是不是就没问题，然后每个分类就只需要一个最大值，

---

## template_category 模块实施方案

### 一、数据模型

**文件：`src/models/template_category.py`（新建）**

```python
from sqlalchemy import String, Integer, ForeignKey, Boolean, DECIMAL, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List

from .base import Base, TimestampMixin


class TemplateCategory(Base, TimestampMixin):
    """加分分类树表"""
    __tablename__ = "template_category"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("template_category.id"), nullable=True
    )
    max_score: Mapped[Optional[float]] = mapped_column(
        DECIMAL(5, 2), nullable=True  # null 表示不限
    )
    is_leaf: Mapped[bool] = mapped_column(
        Boolean, default=True  # TRUE=叶子节点；FALSE=中间节点
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # 自引用关系
    children: Mapped[List["TemplateCategory"]] = relationship(
        "TemplateCategory",
        foreign_keys=[parent_id],
        back_populates="parent",
        lazy="selectin",
    )
    parent: Mapped[Optional["TemplateCategory"]] = relationship(
        "TemplateCategory",
        foreign_keys=[parent_id],
        back_populates="children",
        remote_side="TemplateCategory.id",
    )
```

**注册到 `src/models/__init__.py`：**

```python
from .template_category import TemplateCategory
```

---

### 二、数据库迁移

**新建 migration 文件（Alembic）：**

```python
# alembic/versions/xxxx_add_template_category.py

def upgrade():
    op.create_table(
        "template_category",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("template_category.id"), nullable=True),
        sa.Column("max_score", sa.DECIMAL(5, 2), nullable=True),
        sa.Column("is_leaf", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

def downgrade():
    op.drop_table("template_category")
```

---

### 三、Service 层

**文件：`src/services/template_category_service.py`（新建）**

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from src.models.template_category import TemplateCategory


class TemplateCategoryService:

    @staticmethod
    async def get_tree(db: AsyncSession) -> list:
        """获取完整分类树（仅顶层节点，子节点通过 selectin 懒加载）"""
        result = await db.execute(
            select(TemplateCategory)
            .where(
                TemplateCategory.parent_id.is_(None),
                TemplateCategory.is_active == True,
            )
            .order_by(TemplateCategory.sort_order)
        )
        return result.scalars().all()

    @staticmethod
    async def get_leaf_categories(db: AsyncSession) -> list:
        """获取所有叶子节点，供 Template 绑定时的下拉选项"""
        result = await db.execute(
            select(TemplateCategory)
            .where(
                TemplateCategory.is_leaf == True,
                TemplateCategory.is_active == True,
            )
            .order_by(TemplateCategory.sort_order)
        )
        return result.scalars().all()

    @staticmethod
    async def get_by_id(db: AsyncSession, category_id: int) -> Optional[TemplateCategory]:
        result = await db.execute(
            select(TemplateCategory).where(TemplateCategory.id == category_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_root(
        db: AsyncSession, name: str, max_score: Optional[float], description: Optional[str], sort_order: int = 0
    ) -> TemplateCategory:
        """创建顶层分类（无父节点）"""
        category = TemplateCategory(
            name=name,
            parent_id=None,
            max_score=max_score,
            is_leaf=True,
            sort_order=sort_order,
            description=description,
        )
        db.add(category)
        await db.flush()
        return category

    @staticmethod
    async def create_child(
        db: AsyncSession,
        parent_id: int,
        name: str,
        max_score: Optional[float],
        description: Optional[str],
        sort_order: int = 0,
    ) -> TemplateCategory:
        """
        新增子分类（is_leaf 状态机）：
        - 父节点 is_leaf=FALSE → 直接创建（0 额外查询）
        - 父节点 is_leaf=TRUE  → 查 template 表确认无绑定，通过后创建并将父节点 is_leaf→FALSE
        """
        parent = await TemplateCategoryService.get_by_id(db, parent_id)
        if not parent:
            raise ValueError("父分类不存在")

        if parent.is_leaf:
            # 检查是否已绑定 template（避免叶子节点即绑了模板又成了中间节点）
            from sqlalchemy import text
            bound = await db.execute(
                text("SELECT 1 FROM template WHERE category_id = :cid AND is_active = true LIMIT 1"),
                {"cid": parent_id},
            )
            if bound.first():
                raise ValueError("该分类已绑定模板，不可添加子分类")
            # 将父节点升级为中间节点
            parent.is_leaf = False

        child = TemplateCategory(
            name=name,
            parent_id=parent_id,
            max_score=max_score,
            is_leaf=True,
            sort_order=sort_order,
            description=description,
        )
        db.add(child)
        await db.flush()
        return child

    @staticmethod
    async def update(
        db: AsyncSession,
        category_id: int,
        name: Optional[str] = None,
        max_score: Optional[float] = None,
        description: Optional[str] = None,
        sort_order: Optional[int] = None,
        is_active: Optional[bool] = None,
    ) -> TemplateCategory:
        """修改分类属性（is_leaf 不允许直接修改，由状态机管理）"""
        category = await TemplateCategoryService.get_by_id(db, category_id)
        if not category:
            raise ValueError("分类不存在")
        if name is not None:
            category.name = name
        if max_score is not None:
            category.max_score = max_score
        if description is not None:
            category.description = description
        if sort_order is not None:
            category.sort_order = sort_order
        if is_active is not None:
            category.is_active = is_active
        await db.flush()
        return category

    @staticmethod
    async def delete(db: AsyncSession, category_id: int) -> None:
        """
        删除分类节点（仅叶子节点可删）：
        删除后检查父节点是否还有其他子分类，若无则将父节点 is_leaf→TRUE
        """
        category = await TemplateCategoryService.get_by_id(db, category_id)
        if not category:
            raise ValueError("分类不存在")
        if not category.is_leaf:
            raise ValueError("非叶子节点不可直接删除，请先删除所有子分类")

        parent_id = category.parent_id
        await db.delete(category)
        await db.flush()

        if parent_id:
            sibling_count = await db.execute(
                select(func.count()).where(TemplateCategory.parent_id == parent_id)
            )
            if sibling_count.scalar() == 0:
                parent = await TemplateCategoryService.get_by_id(db, parent_id)
                if parent:
                    parent.is_leaf = True
```

---

### 四、路由层

**文件：`src/app/routes/template_category.py`（新建）**

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.deps import get_db
from src.app import response as R
from src.services.template_category_service import TemplateCategoryService

router = APIRouter(prefix="/api/template-category", tags=["加分分类"])


# ===== Schemas =====

class CreateRootRequest(BaseModel):
    name: str
    maxScore: Optional[float] = None
    description: Optional[str] = None
    sortOrder: int = 0


class CreateChildRequest(BaseModel):
    parentId: int
    name: str
    maxScore: Optional[float] = None
    description: Optional[str] = None
    sortOrder: int = 0


class UpdateCategoryRequest(BaseModel):
    name: Optional[str] = None
    maxScore: Optional[float] = None
    description: Optional[str] = None
    sortOrder: Optional[int] = None
    isActive: Optional[bool] = None


# ===== 工具函数：递归序列化分类树 =====

def _serialize(category) -> dict:
    return {
        "id": category.id,
        "name": category.name,
        "parentId": category.parent_id,
        "maxScore": float(category.max_score) if category.max_score is not None else None,
        "isLeaf": category.is_leaf,
        "sortOrder": category.sort_order,
        "isActive": category.is_active,
        "description": category.description,
        "children": [_serialize(c) for c in sorted(category.children, key=lambda x: x.sort_order)],
    }


# ===== 接口 =====

@router.get("/tree")
async def get_tree(db: AsyncSession = Depends(get_db)):
    """获取完整分类树（管理端展示）"""
    roots = await TemplateCategoryService.get_tree(db)
    return R.success_resp([_serialize(r) for r in roots])


@router.get("/leaves")
async def get_leaf_categories(db: AsyncSession = Depends(get_db)):
    """获取所有叶子节点（绑定模板时的下拉选项）"""
    leaves = await TemplateCategoryService.get_leaf_categories(db)
    return R.success_resp([{
        "id": c.id,
        "name": c.name,
        "maxScore": float(c.max_score) if c.max_score is not None else None,
    } for c in leaves])


@router.post("/root")
async def create_root(req: CreateRootRequest, db: AsyncSession = Depends(get_db)):
    """创建顶层分类（管理员）"""
    category = await TemplateCategoryService.create_root(
        db, name=req.name, max_score=req.maxScore,
        description=req.description, sort_order=req.sortOrder,
    )
    await db.commit()
    return R.created_resp({"id": category.id, "name": category.name})


@router.post("/child")
async def create_child(req: CreateChildRequest, db: AsyncSession = Depends(get_db)):
    """创建子分类（管理员）"""
    try:
        child = await TemplateCategoryService.create_child(
            db, parent_id=req.parentId, name=req.name,
            max_score=req.maxScore, description=req.description,
            sort_order=req.sortOrder,
        )
        await db.commit()
        return R.created_resp({"id": child.id, "name": child.name})
    except ValueError as e:
        return R.bad_request_resp(str(e))


@router.put("/{category_id}")
async def update_category(
    category_id: int,
    req: UpdateCategoryRequest,
    db: AsyncSession = Depends(get_db),
):
    """修改分类（管理员）"""
    try:
        await TemplateCategoryService.update(
            db, category_id,
            name=req.name, max_score=req.maxScore,
            description=req.description, sort_order=req.sortOrder,
            is_active=req.isActive,
        )
        await db.commit()
        return R.success_resp({"id": category_id})
    except ValueError as e:
        return R.bad_request_resp(str(e))


@router.delete("/{category_id}")
async def delete_category(category_id: int, db: AsyncSession = Depends(get_db)):
    """删除叶子分类（管理员）"""
    try:
        await TemplateCategoryService.delete(db, category_id)
        await db.commit()
        return R.success_resp(msg="删除成功")
    except ValueError as e:
        return R.bad_request_resp(str(e))
```

---

### 五、注册路由

**修改 `src/main.py`，在现有路由注册区追加：**

```python
from src.app.routes.template_category import router as template_category_router
# ...
app.include_router(template_category_router)
```

---

### 六、接口清单

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/template-category/tree` | 获取完整分类树（管理端） |
| GET | `/api/template-category/leaves` | 获取叶子节点列表（绑定模板用） |
| POST | `/api/template-category/root` | 创建顶层分类 |
| POST | `/api/template-category/child` | 创建子分类（含 is_leaf 状态机） |
| PUT | `/api/template-category/{id}` | 修改分类属性 |
| DELETE | `/api/template-category/{id}` | 删除叶子分类（含父节点 is_leaf 回退） |

---

### 七、开发顺序

```
1. 新建 src/models/template_category.py
2. 在 src/models/__init__.py 中注册 TemplateCategory
3. 执行 alembic revision --autogenerate -m "add_template_category"
4. 执行 alembic upgrade head（验证建表成功）
5. 新建 src/services/template_category_service.py
6. 新建 src/app/routes/template_category.py
7. 在 src/main.py 中注册路由
8. 启动服务，用 Swagger /docs 手动测试接口
```

---

### 八、注意事项

- `is_leaf` 字段**只能由 Service 状态机修改**，路由层不暴露该字段的直接写入
- `create_child` 中检查父节点是否已绑 template 时，用原生 SQL 查询（此时 `template` 表尚不存在 ORM 模型，下一阶段才建）；待 Template 模型建好后，可改为 ORM 查询
- `max_score=null` 表示该分类不限分值上限，聚合计算时跳过封顶逻辑
- 分类树深度不限，但建议业务上约定 2~3 层（总计 → 一级 → 叶子），避免递归过深