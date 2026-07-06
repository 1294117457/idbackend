"""TemplateCategory 服务（Layer 1）

设计原则：
- 业务规则全部在此；数据库 IO 通过 TemplateCategoryRepository 间接访问
- 抛通用业务异常（NotFoundError / BadRequestError / ConflictError），由全局 exception_handler 翻译为 HTTP 响应
- 事务边界在 service（一句 commit 完成"多个 ORM 修改"）
- DTO 与 ORM 的转换由 schema 完成（to_orm / apply_to），service 拿到的是 ORM

字段语义（v2）：
- `is_bind_template` 由 service 维护，绑 / 解绑时翻转
  - TRUE  = 已绑 template（不可加子、不可再绑）
  - FALSE = 未绑 template（可加子、可绑 template）
- 删除走单事务：预检 active application → 收集后代 → 一次 commit
"""
from decimal import Decimal
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.template_category import TemplateCategory
from src.app.schemas.template_category import (
    TemplateCategoryCreateRequest,
    TemplateCategoryUpdateRequest,
    TemplateCategoryPageQueryRequest,
    TemplateCategoryVO,
    TemplateCategoryListVO,
)
from src.app.schemas.errors import NotFoundError, BadRequestError, ConflictError
from src.repositories.template_category_repo import TemplateCategoryRepository


# ===================== 服务实现 =====================

class TemplateCategoryService:

    # ---------- 读接口 ----------

    @staticmethod
    async def list_all(
        db: AsyncSession,
        *,
        include_inactive: bool = False,
    ) -> List[TemplateCategory]:
        """所有分类平铺列表。"""
        return await TemplateCategoryRepository.list_all(
            db, include_inactive=include_inactive
        )

    @staticmethod
    async def page(
        db: AsyncSession,
        req: TemplateCategoryPageQueryRequest,
    ) -> TemplateCategoryListVO:
        """分页列表 VO（service 直接返回 Page[TemplateCategoryVO]，对齐 file.search_files）。"""
        nodes = await TemplateCategoryRepository.list_all(
            db, include_inactive=req.includeInactive
        )
        total = len(nodes)
        start = (req.pageNum - 1) * req.pageSize
        end = start + req.pageSize
        page_items = [TemplateCategoryVO.from_orm_to_vo(n) for n in nodes[start:end]]
        return TemplateCategoryListVO.from_list_to_page(
            items=page_items,
            total=total,
            page_num=req.pageNum,
            page_size=req.pageSize,
        )

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        category_id: int,
    ) -> TemplateCategory:
        category = await TemplateCategoryRepository.get_by_id(db, category_id)
        if category is None:
            raise NotFoundError(f"分类(id={category_id})不存在")
        return category

    @staticmethod
    async def get_category_path(
        db: AsyncSession,
        category_id: int,
    ) -> List[dict]:
        if await TemplateCategoryRepository.get_by_id(db, category_id) is None:
            raise NotFoundError(f"分类(id={category_id})不存在")
        nodes = await TemplateCategoryRepository.get_path(db, category_id)
        return [{"id": n.id, "name": n.name} for n in nodes]

    @staticmethod
    async def get_leaf_categories(
        db: AsyncSession,
        *,
        include_inactive: bool = False,
    ) -> List[TemplateCategory]:
        return await TemplateCategoryRepository.list_all(
            db, include_inactive=include_inactive, only_bindable=True
        )

    # ---------- 写接口（接 DTO） ----------

    @staticmethod
    async def create(
        db: AsyncSession,
        req: TemplateCategoryCreateRequest,
    ) -> TemplateCategory:
        """统一创建入口：DTO.to_orm() 得到 ORM，业务校验，全事务提交。

        - req.parentId is None → 根节点
        - req.parentId 不为 None → 校验父节点未绑 template
        """
        orm = req.to_orm()

        _ensure_max_score_non_negative(orm.max_score)

        if orm.parent_id is not None:
            parent = await TemplateCategoryRepository.get_by_id(db, orm.parent_id)
            if parent is None:
                raise NotFoundError(f"父节点(id={orm.parent_id})不存在")
            if parent.is_bind_template:
                raise BadRequestError(
                    f"父节点(id={orm.parent_id})已绑定 template，不可继续添加子分类"
                )

        await _ensure_name_unique(db, name=orm.name, parent_id=orm.parent_id)

        db.add(orm)
        await TemplateCategoryRepository.commit(db)
        await TemplateCategoryRepository.refresh(db, orm)
        return orm

    @staticmethod
    async def update(
        db: AsyncSession,
        category_id: int,
        req: TemplateCategoryUpdateRequest,
    ) -> TemplateCategory:
        """修改分类（接 DTO）。

        - is_empty() → 仍然校验存在性后返回当前对象（不写盘）
        - 否则 req.apply_to(category) 把非空字段写回 ORM
        - 全部未动 → 返回原对象（不 commit）
        - 字段修改 → commit + refresh
        """
        if req.is_empty():
            return await TemplateCategoryService.get_by_id(db, category_id)

        category = await TemplateCategoryRepository.get_by_id(db, category_id)
        if category is None:
            raise NotFoundError(f"分类(id={category_id})不存在")

        # name 修改：触发同级唯一校验
        if req.name is not None and req.name != category.name:
            await _ensure_name_unique(
                db,
                name=req.name,
                parent_id=category.parent_id,
                exclude_id=category_id,
            )

        # maxScore 修改：业务校验
        if req.maxScore is not None:
            _ensure_max_score_non_negative(req.maxScore)

        modified = req.apply_to(category)
        if modified:
            await TemplateCategoryRepository.commit(db)
            await TemplateCategoryRepository.refresh(db, category)
        return category

    @staticmethod
    async def bind_template(
        db: AsyncSession,
        category_id: int,
    ) -> TemplateCategory:
        category = await TemplateCategoryRepository.get_by_id(db, category_id)
        if category is None:
            raise NotFoundError(f"分类(id={category_id})不存在")
        if category.is_bind_template:
            return category
        child_count = await TemplateCategoryRepository.count_children(db, category_id)
        if child_count > 0:
            raise BadRequestError(
                f"分类(id={category_id})下已有 {child_count} 个子分类，不可绑定 template"
            )
        await TemplateCategoryRepository.set_bind_template(category, value=True)
        await TemplateCategoryRepository.commit(db)
        await TemplateCategoryRepository.refresh(db, category)
        return category

    @staticmethod
    async def unbind_template(
        db: AsyncSession,
        category_id: int,
    ) -> TemplateCategory:
        category = await TemplateCategoryRepository.get_by_id(db, category_id)
        if category is None:
            raise NotFoundError(f"分类(id={category_id})不存在")
        await TemplateCategoryRepository.unbind_templates(db, category_id)
        await TemplateCategoryRepository.set_bind_template(category, value=False)
        await TemplateCategoryRepository.commit(db)
        await TemplateCategoryRepository.refresh(db, category)
        return category

    @staticmethod
    async def delete(
        db: AsyncSession,
        category_id: int,
    ) -> int:
        if await TemplateCategoryRepository.get_by_id(db, category_id) is None:
            raise NotFoundError(f"分类(id={category_id})不存在")

        descendants = await TemplateCategoryRepository.get_descendants(
            db, category_id, include_self=True
        )
        descendant_ids = [c.id for c in descendants]

        active_count = await TemplateCategoryRepository.count_active_applications(
            db, descendant_ids
        )
        if active_count > 0:
            raise ConflictError(
                f"该分类及其子分类下还有 {active_count} 条未关闭的申请，禁止删除"
            )

        deleted_count = await TemplateCategoryRepository.delete_many(db, descendant_ids)
        await TemplateCategoryRepository.commit(db)
        return deleted_count

    @staticmethod
    async def get_delete_preview(
        db: AsyncSession,
        category_id: int,
    ) -> dict:
        category = await TemplateCategoryRepository.get_by_id(db, category_id)
        if category is None:
            raise NotFoundError(f"分类(id={category_id})不存在")

        descendants = await TemplateCategoryRepository.get_descendants(
            db, category_id, include_self=True
        )
        descendant_ids = [c.id for c in descendants]

        active_count = await TemplateCategoryRepository.count_active_applications(
            db, descendant_ids
        )
        template_count = await TemplateCategoryRepository.count_templates(
            db, descendant_ids
        )

        return {
            "category": category,
            "descendants": descendants,
            "totalDeletedCount": len(descendants),
            "activeApplicationCount": active_count,
            "templateCount": template_count,
        }


# ===================== 内部辅助 =====================

def _ensure_max_score_non_negative(max_score: Decimal) -> None:
    if max_score < 0:
        raise BadRequestError(f"max_score 必须 >= 0，当前值: {max_score}")


async def _ensure_name_unique(
    db: AsyncSession,
    *,
    name: str,
    parent_id: Optional[int],
    exclude_id: Optional[int] = None,
) -> None:
    dup = await TemplateCategoryRepository.find_sibling_by_name(
        db,
        name=name,
        parent_id=parent_id,
        exclude_id=exclude_id,
    )
    if dup is not None:
        raise ConflictError(f"同级下已存在同名分类: {name}")