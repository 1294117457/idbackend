"""计算引擎（ScoreCalculationService，v4）

依赖：pip install simpleeval（安全的数学公式解析，禁止任意代码执行）

输入：
- template: 已 selectinload 完整规则树（template → rules → attributes）
- user_selections: dict，结构：
    { rule_id: attribute_id }      # CONDITION rule：用户选中的 attribute id
    { rule_id: "75.0" }            # TRANSFORM rule：用户输入的数值字符串

输出：min(total, template.max_score)（已封顶）

性能：template.rules 已通过 selectinload 预加载，1 次 SQL 拿到全部数据（无 N+1）。
"""
from decimal import Decimal
from typing import Dict, Union

from simpleeval import simple_eval

from src.models.template import Template, AttributeType


class ScoreCalculationService:
    """计算引擎（v4）"""

    @staticmethod
    def calculate(
        template: Template,
        user_selections: Dict[int, Union[int, str]],
    ) -> float:
        """计算 template 一次申请得分（已封顶）。

        抛 ValueError 当：
        - rule 含 CONDITION attribute 但 score=None（schema 层应已校验，此处兜底）
        - user_input 不在任何 attribute 区间内
        """
        total = 0.0

        for rule in sorted(template.rules, key=lambda r: r.sort_order):
            if not rule.is_active:
                continue

            selected = user_selections.get(rule.id)
            if selected is None:
                continue  # 未填的 rule 不参与计分（与 document 一致：unrequired rule 跳过）

            attrs = sorted(rule.attributes, key=lambda a: a.sort_order)
            if not attrs:
                continue

            attr_type = attrs[0].type

            if attr_type == AttributeType.CONDITION.value:
                # CONDITION 模式：用户选 attribute，加 rule.score
                if any(selected == a.id for a in attrs):
                    if rule.score is None:
                        raise ValueError(
                            f"rule(id={rule.id}) 含 CONDITION attribute 但 score=None"
                        )
                    total += float(rule.score)
            elif attr_type == AttributeType.TRANSFORM.value:
                # TRANSFORM 模式：用户输入数值，按半开半闭区间 [min, max) 匹配 attribute
                try:
                    user_input = float(selected)  # type: ignore[arg-type]
                except (TypeError, ValueError) as e:
                    raise ValueError(
                        f"TRANSFORM rule(id={rule.id}) 的用户输入必须是数值字符串，当前值: {selected!r}"
                    ) from e

                matched = False
                for attr in attrs:
                    if attr.input_min is not None and user_input < float(attr.input_min):
                        continue
                    if attr.input_max is not None and user_input >= float(attr.input_max):
                        continue
                    # simpleeval 安全求值（禁止任意代码执行）
                    total += simple_eval(
                        attr.value or "0",
                        names={"input": user_input},
                    )
                    matched = True
                    break

                if not matched:
                    raise ValueError(
                        f"user_input={user_input} 不在 rule(id={rule.id}) 的任何 attribute 区间内"
                    )
            else:
                # 防御性兜底（DB CHECK 约束应已挡住）
                raise ValueError(
                    f"rule(id={rule.id}) 的 attribute.type 未知: {attr_type!r}"
                )

        return min(total, float(template.max_score))


__all__ = ["ScoreCalculationService"]