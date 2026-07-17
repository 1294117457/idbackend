"""Rule 服务（v5 设计 - action-style 复合接口）

设计原则：
- 业务规则全部在此；DB 通过 RuleRepository 间接访问
- 抛通用业务异常（NotFoundError / BadRequestError / ConflictError）
- 事务边界在 service
- 旧 REST 写接口（create/update/bind_attribute/unbind_attribute）已废弃，
  统一用 save_rule / update_rule / delete_rule_by_id

业务规则（v4）：
- type 必须是 CONDITION / TRANSFORM
- type 与 score 一致：CONDITION 必填 score；TRANSFORM 必须 None
- rule 内 attribute 必须 type 一致（全量替换前硬校验）
"""
from decimal import Decimal
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.models.template import Rule, Attribute, AttributeType
from src.app.schemas.template import (
    RuleCreateRequest,
    RuleUpdateRequest,
    RulePayload,
    RuleSaveRequest,
    RuleSaveUpdateRequest,
    RuleDeleteRequest,
    RuleSaveResponse,
    RuleDetailVO,
    AttributeVO,
)
from src.app.schemas.errors import (
    NotFoundError,
    BadRequestError,
    ConflictError,
)
from src.repositories.rule_repo import RuleRepository
from src.repositories.attribute_repo import AttributeRepository


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
    """Rule 服务（v5）"""

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

    # ---------- v5 写 ----------

    @staticmethod
    async def save_rule(
        db: AsyncSession,
        req: RuleSaveRequest,
    ) -> RuleSaveResponse:
        """POST /rule/save：新建 rule + 一次性绑 attribute（单事务）

        事务边界：
        1. type-score 校验
        2. attributeIds 全部存在 + type 一致
        3. insert rule
        4. commit（拿到 rule.id）
        5. replace_bound_attributes
        6. commit
        7. 组装 RuleSaveResponse
        """
        _validate_type_score(req.rule.type, req.rule.score)
        await RuleService._validate_attribute_type_consistency(
            db, req.rule.type, req.attributeIds,
        )

        rule = req.rule.to_orm()
        db.add(rule)
        await RuleRepository.commit(db)
        await RuleRepository.refresh(db, rule)

        rule_id = rule.id
        if req.attributeIds:
            await RuleRepository.replace_bound_attributes(db, rule_id, req.attributeIds)
            await RuleRepository.commit(db)

        return await RuleService._build_save_response(db, rule_id)

    @staticmethod
    async def update_rule(
        db: AsyncSession,
        req: RuleSaveUpdateRequest,
    ) -> RuleSaveResponse:
        """POST /rule/update：编辑 rule + 重置 attribute 绑定（DIFF，单事务）

        事务边界：
        1. 校验 rule 存在
        2. type-score 校验
        3. attributeIds 全部存在 + type 一致
        4. apply_to 覆盖字段
        5. replace_bound_attributes
        6. commit
        7. 组装 RuleSaveResponse
        """
        rule = await RuleService.get_by_id(db, req.ruleId)

        _validate_type_score(req.rule.type, req.rule.score)
        await RuleService._validate_attribute_type_consistency(
            db, req.rule.type, req.attributeIds,
        )

        req.rule.apply_to(rule)
        await RuleRepository.replace_bound_attributes(db, req.ruleId, req.attributeIds)
        await RuleRepository.commit(db)

        return await RuleService._build_save_response(db, req.ruleId)

    @staticmethod
    async def delete_rule_by_id(
        db: AsyncSession,
        req: RuleDeleteRequest,
    ) -> None:
        """POST /rule/delete：删除 rule（带引用检查）

        - 预检：是否被 template 绑定 → ConflictError
        - FK CASCADE 自动清理 rule_attribute 行
        """
        rule = await RuleService.get_by_id(db, req.ruleId)

        bound_count = await RuleRepository.count_bound_templates(db, req.ruleId)
        if bound_count > 0:
            raise ConflictError(
                f"该 rule 被 {bound_count} 个 template 绑定，无法删除。请先解绑。"
            )

        await RuleRepository.delete(db, req.ruleId)
        await RuleRepository.commit(db)

    # ---------- 内部辅助 ----------

    @staticmethod
    async def _validate_attribute_type_consistency(
        db: AsyncSession,
        rule_type: str,
        attribute_ids: List[int],
    ) -> None:
        """硬校验：所有 attributeIds 必须存在 + type == rule_type

        v4 唯一硬校验：rule.type == attribute.type
        单事务内、DIFF 替换前必须保证一致性。
        """
        deduped = list({aid for aid in attribute_ids if aid is not None})
        if not deduped:
            return

        rows = (await db.execute(
            select(Attribute).where(Attribute.id.in_(deduped))
        )).scalars().all()

        existing_map = {a.id: a for a in rows}

        # 1. 不存在
        missing = [aid for aid in deduped if aid not in existing_map]
        if missing:
            raise NotFoundError(f"attribute 不存在：id={missing}")

        # 2. type 不一致
        mismatched = [
            f"id={a.id}.type={a.type}" for a in rows
            if a.type != rule_type
        ]
        if mismatched:
            raise BadRequestError(
                f"rule.type={rule_type} 与以下 attribute.type 不一致：{mismatched}。"
                f"硬校验：rule 内 attribute 必须 type 相同。"
            )

    @staticmethod
    async def _build_save_response(
        db: AsyncSession,
        rule_id: int,
    ) -> RuleSaveResponse:
        """组装 RuleSaveResponse（与 TemplateService._build_save_response 对称）"""
        rule = await RuleService.get_with_attributes(db, rule_id)

        attr_vos = [
            AttributeVO.from_orm_to_vo(a)
            for a in sorted(rule.attributes, key=lambda a: a.sort_order)
        ]
        rule_detail_vo = RuleDetailVO.from_orm_to_vo(rule, attr_vos)

        return RuleSaveResponse(
            ruleId=rule_id,
            rule=rule_detail_vo,
            boundAttributeIds=[a.id for a in attr_vos],
        )


__all__ = ["RuleService"]
