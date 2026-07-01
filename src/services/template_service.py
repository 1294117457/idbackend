"""模板服务"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from src.models import ScoreTemplate, ScoreTemplateRule, RuleAttribute, DemandTemplate, FieldConfig


class TemplateService:
    """模板服务"""

    @staticmethod
    async def get_templates(
        db: AsyncSession,
        score_type: Optional[int] = None,
        is_active: bool = True,
    ) -> List[ScoreTemplate]:
        """获取模板列表"""
        query = select(ScoreTemplate).where(ScoreTemplate.is_active == is_active)

        if score_type is not None:
            query = query.where(ScoreTemplate.score_type == score_type)

        query = query.order_by(ScoreTemplate.id)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_template_by_id(
        db: AsyncSession,
        template_id: int,
    ) -> Optional[ScoreTemplate]:
        """根据ID获取模板"""
        result = await db.execute(
            select(ScoreTemplate).where(ScoreTemplate.id == template_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_template_rules(
        db: AsyncSession,
        template_id: int,
    ) -> List[ScoreTemplateRule]:
        """获取模板的计分规则"""
        result = await db.execute(
            select(ScoreTemplateRule).where(
                ScoreTemplateRule.template_id == template_id
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def create_template(
        db: AsyncSession,
        template_name: str,
        template_type: str,
        template_max_score: float,
        score_type: int = 0,
        input_unit: str = "",
        description: str = "",
        created_by: str = "system",
        review_count: int = 1,
    ) -> ScoreTemplate:
        """创建模板"""
        template = ScoreTemplate(
            template_name=template_name,
            template_type=template_type,
            score_type=score_type,
            template_max_score=template_max_score,
            input_unit=input_unit,
            description=description,
            created_by=created_by,
            review_count=review_count,
        )
        db.add(template)
        await db.commit()
        await db.refresh(template)
        return template

    @staticmethod
    async def get_rule_attributes(
        db: AsyncSession,
        rule_id: int,
    ) -> List[RuleAttribute]:
        """获取规则的属性"""
        result = await db.execute(
            select(RuleAttribute).join(
                ScoreTemplateRule.attributes
            ).where(
                ScoreTemplateRule.id == rule_id
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def calculate_score(
        rule: ScoreTemplateRule,
        user_input: float,
        attribute: Optional[RuleAttribute] = None,
    ) -> float:
        """计算分数"""
        if rule.rule_type == "CONDITION":
            # 条件型: 返回固定分数
            return float(rule.rule_score or 0)

        elif rule.rule_type == "TRANSFORM" and attribute:
            # 转换型: 按公式计算
            formula = attribute.attribute_value or ""
            if formula and "INPUT" in formula:
                # 公式格式: "100-(4-INPUT)/0.3*11"
                try:
                    return float(eval(formula.replace("INPUT", str(user_input))))
                except:
                    return 0
            return 0

        return 0

    @staticmethod
    async def get_demand_templates(
        db: AsyncSession,
        is_active: bool = True,
    ) -> List[DemandTemplate]:
        """获取需求模板"""
        query = select(DemandTemplate).where(DemandTemplate.is_active == is_active)
        query = query.order_by(DemandTemplate.sort_order)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_field_configs(
        db: AsyncSession,
        field_type: Optional[str] = None,
    ) -> List[FieldConfig]:
        """获取字段配置"""
        query = select(FieldConfig).where(FieldConfig.is_active == True)

        if field_type:
            query = query.where(FieldConfig.field_type == field_type)

        query = query.order_by(FieldConfig.sort_order)
        result = await db.execute(query)
        return list(result.scalars().all())
