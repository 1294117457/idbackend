"""模板服务"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from src.models import ScoreTemplate, ScoreTemplateRule, RuleAttribute, DemandTemplate, FieldConfig, FieldSubcategory


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

    @staticmethod
    async def get_field_config_by_id(
        db: AsyncSession,
        config_id: int,
    ) -> Optional[FieldConfig]:
        """根据ID获取字段配置"""
        result = await db.execute(
            select(FieldConfig).where(FieldConfig.id == config_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_field_config(
        db: AsyncSession,
        field_key: str,
        display_name: str,
        field_type: str,
        max_score: Optional[float] = None,
        conditions: Optional[list] = None,
        description: Optional[str] = None,
        college_code: Optional[str] = None,
        academic_year: Optional[int] = None,
        sort_order: int = 0,
        created_by: str = "system",
    ) -> FieldConfig:
        """创建字段配置"""
        config = FieldConfig(
            field_key=field_key,
            display_name=display_name,
            field_type=field_type,
            max_score=max_score,
            conditions=conditions or [],
            description=description,
            college_code=college_code,
            academic_year=academic_year,
            sort_order=sort_order,
            created_by=created_by,
        )
        db.add(config)
        await db.commit()
        await db.refresh(config)
        return config

    @staticmethod
    async def update_field_config(
        db: AsyncSession,
        config_id: int,
        **kwargs,
    ) -> Optional[FieldConfig]:
        """更新字段配置"""
        config = await TemplateService.get_field_config_by_id(db, config_id)
        if not config:
            return None

        for key, value in kwargs.items():
            if hasattr(config, key) and value is not None:
                setattr(config, key, value)

        await db.commit()
        await db.refresh(config)
        return config

    @staticmethod
    async def delete_field_config(
        db: AsyncSession,
        config_id: int,
    ) -> bool:
        """删除字段配置"""
        config = await TemplateService.get_field_config_by_id(db, config_id)
        if not config:
            return False

        config.is_active = False
        await db.commit()
        return True

    # ========== FieldSubcategory ==========

    @staticmethod
    async def get_subcategories(
        db: AsyncSession,
        field_id: Optional[int] = None,
    ) -> List[FieldSubcategory]:
        """获取字段细分"""
        query = select(FieldSubcategory).where(FieldSubcategory.is_active == True)

        if field_id:
            query = query.where(FieldSubcategory.field_id == field_id)

        query = query.order_by(FieldSubcategory.sort_order)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_subcategory_by_id(
        db: AsyncSession,
        subcategory_id: int,
    ) -> Optional[FieldSubcategory]:
        """根据ID获取字段细分"""
        result = await db.execute(
            select(FieldSubcategory).where(FieldSubcategory.id == subcategory_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_subcategory(
        db: AsyncSession,
        field_id: int,
        sub_key: str,
        display_name: str,
        max_score: float,
        description: Optional[str] = None,
        sort_order: int = 0,
    ) -> FieldSubcategory:
        """创建字段细分"""
        subcategory = FieldSubcategory(
            field_id=field_id,
            sub_key=sub_key,
            display_name=display_name,
            max_score=max_score,
            description=description,
            sort_order=sort_order,
        )
        db.add(subcategory)
        await db.commit()
        await db.refresh(subcategory)
        return subcategory

    @staticmethod
    async def update_subcategory(
        db: AsyncSession,
        subcategory_id: int,
        **kwargs,
    ) -> Optional[FieldSubcategory]:
        """更新字段细分"""
        subcategory = await TemplateService.get_subcategory_by_id(db, subcategory_id)
        if not subcategory:
            return None

        for key, value in kwargs.items():
            if hasattr(subcategory, key) and value is not None:
                setattr(subcategory, key, value)

        await db.commit()
        await db.refresh(subcategory)
        return subcategory

    @staticmethod
    async def delete_subcategory(
        db: AsyncSession,
        subcategory_id: int,
    ) -> bool:
        """删除字段细分"""
        subcategory = await TemplateService.get_subcategory_by_id(db, subcategory_id)
        if not subcategory:
            return False

        subcategory.is_active = False
        await db.commit()
        return True
