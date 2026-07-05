"""Rule 服务（v4 设计）

设计原则：
- 业务规则全部在此；DB 通过 RuleRepository 间接访问
- 抛通用业务异常（NotFoundError / BadRequestError / ConflictError）
- 事务边界在 service

业务规则（v4）：
- type 必须是 CONDITION / TRANSFORM
- type 与 score 一致：CONDITION 必填 score；TRANSFORM 必须 None
- bind_attribute 时硬校验 rule.type == attribute.type（v4 唯一硬校验）
"""
from decimal import Decimal
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.template import Rule, AttributeType
from src.app.schemas.template import (
    RuleCreateRequest,
    RuleUpdateRequest,
)
from src.app.schemas.errors import (
    NotFoundError,
    BadRequestError,
)
from src.repositories.rule_repo import RuleRepository
from src.repositories.attribute_repo import AttributeRepository
from src.services.attribute_service import AttributeService


# ============================================================
# 业务校验
# ============================================================

def _validate_type_score(type: str, score: Optional[Decimal]) -> None:
    """type 与 score 的一致性校验（v4 核心规则）。"""
    if type == AttributeType.CONDITION.value:
        if score is None:
            raise BadRequestError("CONDITION 类型 rule 的 score 必填")
    elif type == AttributeType.TRANSFORM.value:
        if score is not None:
            raise BadRequestError("TRANSFORM 类型 rule 的 score 必须为 None（分数由 attribute.value 公式动态计算）")
    else:
        raise BadRequestError(f"type 必须是 CONDITION / TRANSFORM，当前值: {type}")


# ============================================================
# 服务实现
# ============================================================

class RuleService:
    """Rule 服务（v4）"""

    @staticmethod
    def validate(req: RuleCreateRequest) -> None:
        """业务校验（DTO 层 Pydantic 校验输入格式，本方法校验 type-score 一致性）。"""
        _validate_type_score(req.type, req.score)

    # ---------- 读 ----------

    @staticmethod
    async def list_paged(
        db: AsyncSession,
        *,
        is_active: Optional[bool] = True,
        rule_type: Optional[str] = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> tuple[List[Rule], int]:
        """分页列表 + 总数。"""
        total = await RuleRepository.count(
            db, is_active=is_active, rule_type=rule_type,
        )
        rules = await RuleRepository.list_paged(
            db,
            is_active=is_active,
            rule_type=rule_type,
            offset=(page_num - 1) * page_size,
            limit=page_size,
        )
        return rules, total

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        rule_id: int,
    ) -> Rule:
        rule = await RuleRepository.get_by_id(db, rule_id)
        if rule is None:
            raise NotFoundError(f"规则(id={rule_id})不存在")
        return rule

    @staticmethod
    async def get_with_attributes(
        db: AsyncSession,
        rule_id: int,
    ) -> Rule:
        rule = await RuleRepository.get_with_attributes(db, rule_id)
        if rule is None:
            raise NotFoundError(f"规则(id={rule_id})不存在")
        return rule

    # ---------- 写 ----------

    @staticmethod
    async def create(
        db: AsyncSession,
        req: RuleCreateRequest,
    ) -> Rule:
        """创建 rule。"""
        RuleService.validate(req)  # type-score 一致性

        rule = req.to_orm()
        db.add(rule)
        await RuleRepository.commit(db)
        await RuleRepository.refresh(db, rule)
        return rule

    @staticmethod
    async def update(
        db: AsyncSession,
        rule_id: int,
        req: RuleUpdateRequest,
    ) -> Rule:
        """修改 rule。"""
        rule = await RuleService.get_by_id(db, rule_id)

        # 修改 type 或 score 时，校验 type-score 一致性
        if req.type is not None or req.score is not None:
            new_type = req.type if req.type is not None else rule.type
            new_score = req.score if req.score is not None else rule.score
            _validate_type_score(new_type, new_score)

        modified = req.apply_to(rule)
        if modified:
            await RuleRepository.commit(db)
            await RuleRepository.refresh(db, rule)
        return rule

    @staticmethod
    async def delete(
        db: AsyncSession,
        rule_id: int,
    ) -> None:
        """删除 rule。

        - FK CASCADE 自动清理 template_rule / rule_attribute 行
        - 不影响已有 application（application 不直接引用 rule）
        """
        await RuleService.get_by_id(db, rule_id)  # 校验存在
        await RuleRepository.delete(db, rule_id)
        await RuleRepository.commit(db)

    # ---------- 关联操作 ----------

    @staticmethod
    async def bind_attribute(
        db: AsyncSession,
        rule_id: int,
        attribute_id: int,
    ) -> None:
        """rule 绑 attribute（v4 唯一硬校验：rule.type == attribute.type）。

        由这条校验自然保证"同一 rule 内 attribute 不可混用"。
        """
        rule = await RuleService.get_by_id(db, rule_id)
        attribute = await AttributeRepository.get_by_id(db, attribute_id)
        if attribute is None:
            raise NotFoundError(f"属性(id={attribute_id})不存在")

        if rule.type != attribute.type:
            raise BadRequestError(
                f"rule.type 与 attribute.type 不一致："
                f"rule(id={rule_id}).type={rule.type}, "
                f"attribute(id={attribute_id}).type={attribute.type}。"
                f"v4 唯一硬校验：rule 与其绑定的 attribute 必须 type 一致。"
            )

        link = await RuleRepository.bind_attribute(db, rule_id, attribute_id)
        if link is not None:
            await RuleRepository.commit(db)

    @staticmethod
    async def unbind_attribute(
        db: AsyncSession,
        rule_id: int,
        attribute_id: int,
    ) -> None:
        """解绑 attribute。"""
        await RuleRepository.unbind_attribute(db, rule_id, attribute_id)
        await RuleRepository.commit(db)


__all__ = ["RuleService"]


# ============================================================
# 模块加载即 patch：给 AttributeService 注入 or_none 版本
# ============================================================
# 设计动机：避免 RuleService.bind_attribute 出现循环依赖
# （rule_service 引用 attribute_service 但同时 attribute_service 也可以反向引用 rule_service）

async def _attribute_get_by_id_or_none(db: AsyncSession, attribute_id: int):
    """AttributeService.get_by_id_or_none —— 找不到返回 None 而不是抛异常"""
    try:
        return await AttributeService.get_by_id(db, attribute_id)
    except NotFoundError:
        return None


AttributeService.get_by_id_or_none = staticmethod(_attribute_get_by_id_or_none)  # type: ignore[attr-defined]  # noqa: E402