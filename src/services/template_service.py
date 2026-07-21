"""Template 服务（Layer 2 - 聚合根）

设计原则：
- 业务规则全部在此；数据库 IO 通过 TemplateRepository 间接访问
- 抛通用业务异常（NotFoundError / BadRequestError / ConflictError），由全局 exception_handler 翻译
- 事务边界在 service（一句话 commit 完成"多个 ORM 修改"）
- DTO 与 ORM 的转换由 schema 完成（to_orm / apply_to），service 拿到的是 ORM
- template 不校验 type 一致性（业务允许混用 CONDITION + TRANSFORM rule，软提示返回 is_mixed_type）

v5：新增 save_template / update_template / delete_template_by_id 三个方法，
统一处理"template 字段 + rule 绑定"的复合操作（单事务）。
"""
import logging
from decimal import Decimal
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.models.template import Template
from src.models.template_category import TemplateCategory
from src.infra.storage import Storage
from src.infra.rich_text_service import RichTextService
from src.app.schemas.template import (
    TemplateCreateRequest,
    TemplateUpdateRequest,
    TemplateListQueryRequest,
    TemplateSaveRequest,
    TemplateSaveUpdateRequest,
    TemplateDeleteRequest,
    TemplatePayload,
    TemplateSaveResponse,
    TemplateVO,
    TemplateDetailVO,
)
from src.app.schemas.errors import (
    NotFoundError,
    BadRequestError,
)
from src.repositories.template_repo import TemplateRepository
from src.repositories.template_category_repo import TemplateCategoryRepository

logger = logging.getLogger(__name__)


# ============================================================
# 服务实现
# ============================================================

class TemplateService:
    """Template 服务（Layer 2）"""

    # ---------- 读 ----------

    @staticmethod
    async def list_paged(
        db: AsyncSession,
        storage: Storage,
        rich_text_service: RichTextService,
        req: TemplateListQueryRequest,
    ) -> tuple[List[Template], int]:
        total = await TemplateRepository.count(
            db,
            category_id=req.categoryId,
            is_active=req.isActive,
        )
        templates = await TemplateRepository.list_paged(
            db,
            category_id=req.categoryId,
            is_active=req.isActive,
            offset=(req.pageNum - 1) * req.pageSize,
            limit=req.pageSize,
        )
        for t in templates:
            t.description = rich_text_service.sign_html(
                t.description,
                entity_type="template",
                entity_id=t.id,
            )
        return templates, total

    @staticmethod
    async def list_by_category(
        db: AsyncSession,
        storage: Storage,
        rich_text_service: RichTextService,
        category_id: int,
        is_active: bool = True,
    ) -> List[Template]:
        """按分类 ID 列出模板（学生端选择 template）。

        返回前做富文本占位替换。
        """
        templates = await TemplateRepository.list_by_category(
            db, category_id, is_active=is_active,
        )
        for t in templates:
            t.description = rich_text_service.sign_html(
                t.description,
                entity_type="template",
                entity_id=t.id,
            )
        return templates

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        storage: Storage,
        rich_text_service: RichTextService,
        template_id: int,
    ) -> Template:
        """单条查询，找不到抛 NotFoundError。

        返回前做富文本占位替换。
        """
        template = await TemplateRepository.get_by_id(db, template_id)
        if template is None:
            raise NotFoundError(f"模板(id={template_id})不存在")
        template.description = rich_text_service.sign_html(
            template.description,
            entity_type="template",
            entity_id=template_id,
        )
        return template

    @staticmethod
    async def get_with_rules(
        db: AsyncSession,
        storage: Storage,
        rich_text_service: RichTextService,
        template_id: int,
    ) -> Template:
        """加载完整规则树（template → rules → attributes）。

        使用 selectinload，3 条 SQL 拿到全部数据，无 N+1。

        返回前做富文本占位替换。
        """
        template = await TemplateRepository.get_with_rules(db, template_id)
        if template is None:
            raise NotFoundError(f"模板(id={template_id})不存在")
        template.description = rich_text_service.sign_html(
            template.description,
            entity_type="template",
            entity_id=template_id,
        )
        return template

    @staticmethod
    async def is_mixed_type(
        db: AsyncSession,
        template_id: int,
    ) -> bool:
        """判断 template 是否混用了不同 type 的 rule（业务合法，仅软提示）。"""
        types = await TemplateRepository.get_rule_types(db, template_id)
        return len(set(types)) > 1

    # ---------- 写 ----------

    @staticmethod
    async def create(
        db: AsyncSession,
        storage: Storage,
        rich_text_service: RichTextService,
        req: TemplateCreateRequest,
    ) -> Template:
        """创建模板。

        - 校验分类存在
        - 校验分类未绑 template？v4 不限制：允许同一分类挂多个 template
        - 调 TemplateCategoryService.bind_template 把分类的 is_bind_template 翻为 TRUE（幂等）
        - v9：返回前对 description 做占位替换
        """
        category = await TemplateCategoryRepository.get_by_id(db, req.categoryId)
        if category is None:
            raise NotFoundError(f"分类(id={req.categoryId})不存在")

        # 校验分类无子分类才可绑 template（必须在 commit 前，否则 template 已落盘）
        child_count = await TemplateCategoryRepository.count_children(db, req.categoryId)
        if child_count > 0:
            raise BadRequestError(
                f"分类(id={req.categoryId})下已有 {child_count} 个子分类，不可绑定 template"
            )

        template = req.to_orm()

        db.add(template)
        await TemplateRepository.commit(db)
        await TemplateRepository.refresh(db, template)

        # v10：占位迁移 temp->最终路径
        template.description = rich_text_service.process_html(
            template.description,
            entity_type="template",
            entity_id=template.id,
        )
        await TemplateRepository.commit(db)

        # 翻分类 is_bind_template = TRUE（幂等）
        from src.services.template_category_service import TemplateCategoryService
        await TemplateCategoryService.bind_template(db, req.categoryId)

        # v9：占位替换（新建场景通常没有富文本，但保持接口一致性）
        template.description = rich_text_service.sign_html(
            template.description,
            entity_type="template",
            entity_id=template.id,
        )
        return template

    @staticmethod
    async def update(
        db: AsyncSession,
        storage: Storage,
        rich_text_service: RichTextService,
        template_id: int,
        req: TemplateUpdateRequest,
    ) -> Template:
        """修改模板。"""
        template = await TemplateService.get_by_id(
            db, storage, rich_text_service, template_id,
        )

        modified = req.apply_to(template)
        if modified:
            # v10：占位迁移 temp->最终路径
            template.description = rich_text_service.process_html(
                template.description,
                entity_type="template",
                entity_id=template_id,
            )
            await TemplateRepository.commit(db)
            await TemplateRepository.refresh(db, template)
        return template

    @staticmethod
    async def bind_rule(
        db: AsyncSession,
        storage: Storage,
        rich_text_service: RichTextService,
        template_id: int,
        rule_id: int,
    ) -> dict:
        """绑定 rule 到 template（v4 软提示策略）。

        - 不校验 rule.type 一致性（业务允许混用 ACM 类模板）
        - 返回 { bound, is_mixed_type } 给前端做软提示
        - 混用时打 warning 日志，不抛异常
        """
        # 校验存在性
        await TemplateService.get_by_id(
            db, storage, rich_text_service, template_id,
        )

        from src.services.rule_service import RuleService
        await RuleService.get_by_id(db, rule_id)  # 不存在抛 NotFoundError

        # 绑定（幂等）
        link = await TemplateRepository.bind_rule(db, template_id, rule_id)
        if link is not None:
            await TemplateRepository.commit(db)

        # 计算 is_mixed_type（每次实时算）
        types = await TemplateRepository.get_rule_types(db, template_id)
        is_mixed = len(set(types)) > 1

        if is_mixed:
            logger.warning(
                "template(id=%s) 混用了 rule.type: %s",
                template_id,
                sorted(set(types)),
            )

        return {"bound": True, "is_mixed_type": is_mixed}

    @staticmethod
    async def unbind_rule(
        db: AsyncSession,
        storage: Storage,
        rich_text_service: RichTextService,
        template_id: int,
        rule_id: int,
    ) -> None:
        """解绑 rule（不影响 rule 本体）。"""
        await TemplateService.get_by_id(
            db, storage, rich_text_service, template_id,
        )
        await TemplateRepository.unbind_rule(db, template_id, rule_id)
        await TemplateRepository.commit(db)

    @staticmethod
    async def delete(
        db: AsyncSession,
        storage: Storage,
        rich_text_service: RichTextService,
        template_id: int,
    ) -> None:
        """删除 template。

        - application 与 template 已解耦（无 FK）：
          删除 template 不会触碰 applications 表的任何行，
          application 上的 template_id 字段保留作为历史引用。
        - 物理删除（template_rule 表的 FK CASCADE 自动清理绑定行）
        - 解绑后：检查 category 下 template 数量归零 → 翻 is_bind_template 回 FALSE
        - 删除关联的富文本文件（MinIO，按 prefix 清理）
        """
        template = await TemplateService.get_by_id(
            db, storage, rich_text_service, template_id,
        )

        category_id = template.category_id
        await TemplateRepository.delete(db, template_id)
        await TemplateRepository.commit(db)

        # 删除富文本文件（MinIO，按 prefix 清理）
        rich_text_service.delete_by_entity(entity_type="template", entity_id=template_id)

        # 解绑：检查 category 下是否还有其它 template，没有就翻回 FALSE
        remaining = await TemplateRepository.count(
            db, category_id=category_id, is_active=True,
        )
        if remaining == 0:
            from src.services.template_category_service import TemplateCategoryService
            await TemplateCategoryService.unbind_template(db, category_id)

    # ---------- v5 action-style 统一接口 ----------

    @staticmethod
    async def save_template(
        db: AsyncSession,
        storage: Storage,
        rich_text_service: RichTextService,
        req: TemplateSaveRequest,
    ) -> TemplateSaveResponse:
        """POST /save：新建 template + 一次性绑 rule（单事务）

        事务边界：
        1. 校验 category 存在 + 叶子节点
        2. 校验 ruleIds 全部存在
        3. insert template（不带 rule）
        4. flush（拿到 template_id）
        5. replace_bound_rules(template_id, req.ruleIds)
        6. commit
        7. 翻 category.is_bind_template = TRUE（幂等，category_service 内部事务）
        8. 重新加载 template（含 rules）→ 组装 TemplateSaveResponse（v9：含 description 替换）
        """
        await TemplateService._assert_category_leaf(db, req.template.categoryId)
        await TemplateService._validate_rule_ids(db, req.ruleIds)

        template = req.template.to_orm()
        await TemplateRepository.insert(db, template)
        await TemplateRepository.commit(db)
        await TemplateRepository.refresh(db, template)

        template_id = template.id

        # v10：占位迁移 temp->最终路径
        template.description = rich_text_service.process_html(
            template.description,
            entity_type="template",
            entity_id=template_id,
        )
        await TemplateRepository.commit(db)
        if req.ruleIds:
            await TemplateRepository.replace_bound_rules(db, template_id, req.ruleIds)
            await TemplateRepository.commit(db)

        # 翻分类 is_bind_template = TRUE（幂等）
        from src.services.template_category_service import TemplateCategoryService
        await TemplateCategoryService.bind_template(db, req.template.categoryId)

        return await TemplateService._build_save_response(
            db, storage, rich_text_service, template_id,
        )

    @staticmethod
    async def update_template(
        db: AsyncSession,
        storage: Storage,
        rich_text_service: RichTextService,
        req: TemplateSaveUpdateRequest,
    ) -> TemplateSaveResponse:
        template = await TemplateService.get_by_id(
            db, storage, rich_text_service, req.templateId,
        )
        old_category_id = template.category_id

        if template.category_id != req.template.categoryId:
            await TemplateService._assert_category_leaf(db, req.template.categoryId)
        await TemplateService._validate_rule_ids(db, req.ruleIds)

        req.template.apply_to(template)

        # v10：占位迁移 temp->最终路径
        template.description = rich_text_service.process_html(
            template.description,
            entity_type="template",
            entity_id=req.templateId,
        )

        await TemplateRepository.replace_bound_rules(db, req.templateId, req.ruleIds)
        await TemplateRepository.commit(db)

        # category 切换 → 维护 is_bind_template 字段
        if old_category_id != req.template.categoryId:
            from src.services.template_category_service import TemplateCategoryService
            # 旧的：检查是否还有 template，没有就翻 FALSE
            old_remaining = await TemplateRepository.count(
                db, category_id=old_category_id, is_active=True,
            )
            if old_remaining == 0:
                await TemplateCategoryService.unbind_template(db, old_category_id)
            # 新的：翻 TRUE（幂等）
            await TemplateCategoryService.bind_template(db, req.template.categoryId)

        return await TemplateService._build_save_response(
            db, storage, rich_text_service, req.templateId,
        )

    @staticmethod
    async def delete_template_by_id(
        db: AsyncSession,
        storage: Storage,
        rich_text_service: RichTextService,
        req: TemplateDeleteRequest,
    ) -> None:
        await TemplateService.delete(
            db, storage, rich_text_service, req.templateId,
        )

    # ---------- v5 内部辅助 ----------

    @staticmethod
    async def _assert_category_leaf(db: AsyncSession, category_id: int) -> None:
        """校验分类存在 + 是叶子节点（与既有 TemplateService.create 一致）"""
        category = await TemplateCategoryRepository.get_by_id(db, category_id)
        if category is None:
            raise NotFoundError(f"分类(id={category_id})不存在")
        child_count = await TemplateCategoryRepository.count_children(db, category_id)
        if child_count > 0:
            raise BadRequestError(
                f"分类(id={category_id})下已有 {child_count} 个子分类，不可绑定 template"
            )

    @staticmethod
    async def _validate_rule_ids(db: AsyncSession, rule_ids: List[int]) -> None:
        from src.models.template import Rule

        deduped = list({rid for rid in rule_ids if rid is not None})
        if not deduped:
            return
        rows = (await db.execute(
            select(Rule.id).where(Rule.id.in_(deduped))
        )).scalars().all()
        existing = set(rows)
        missing = [rid for rid in deduped if rid not in existing]
        if missing:
            raise BadRequestError(
                f"rule 不存在或已禁用：id={missing}"
            )

    @staticmethod
    async def _build_save_response(
        db: AsyncSession,
        storage: Storage,
        rich_text_service: RichTextService,
        template_id: int,
    ) -> TemplateSaveResponse:
        """加载 template（含 rules）→ 组装 TemplateSaveResponse

        复用 get_with_rules + is_mixed_type 的逻辑（v9：含 description 占位替换）。
        """
        template = await TemplateService.get_with_rules(
            db, storage, rich_text_service, template_id,
        )
        is_mixed = await TemplateService.is_mixed_type(db, template_id)

        sorted_rules = sorted(template.rules, key=lambda r: r.sort_order)
        detail_vo = TemplateDetailVO.from_template_with_rules(
            template, sorted_rules, is_mixed
        )
        bound_ids = [rule.id for rule in sorted_rules]

        return TemplateSaveResponse(
            templateId=template_id,
            template=detail_vo,
            boundRuleIds=bound_ids,
            isMixedType=is_mixed,
        )

    # ---------- 兼容旧接口（application 路由层仍在用旧字段，下个迭代会清理） ----------

    @staticmethod
    async def get_templates(db: AsyncSession) -> List[Template]:
        """兼容旧 application 路由：返回所有启用模板（不分页、不带规则树）。

        下个迭代 application 路由完全切到 v4 后此方法可删除。
        """
        return await TemplateRepository.list_paged(
            db, is_active=True, offset=0, limit=10000,
        )

    @staticmethod
    async def get_template_type_by_name(
        db: AsyncSession,
        template_name: str,
    ) -> str:
        """兼容旧 application 路由：按模板名推断 type。

        v4 模板无 type 字段，此处用 rule.type 的众数作为推断（业务提示用）。
        """
        from sqlalchemy import func

        from src.models.template import TemplateRule

        stmt = (
            select(func.distinct(__import__("src.models.template", fromlist=["Rule"]).Rule.type))
            .select_from(Template)
            .join(TemplateRule, TemplateRule.template_id == Template.id)
            .join(
                __import__("src.models.template", fromlist=["Rule"]).Rule,
                __import__("src.models.template", fromlist=["Rule"]).Rule.id == TemplateRule.rule_id,
            )
            .where(Template.name == template_name)
            .where(Template.is_active == True)
        )
        result = await db.execute(stmt)
        types = [row[0] for row in result.all()]
        if not types:
            return "CONDITION"
        return types[0]


# ============================================================
# 内部辅助
# ============================================================

def _ensure_max_score_non_negative(max_score: Decimal) -> None:
    if max_score < 0:
        raise BadRequestError(f"max_score 必须 >= 0，当前值: {max_score}")