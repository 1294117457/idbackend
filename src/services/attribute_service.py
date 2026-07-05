"""Attribute 服务（v4 设计）

设计原则：
- 业务规则全部在此；DB 通过 AttributeRepository 间接访问
- 抛通用业务异常（NotFoundError / BadRequestError / ConflictError）
- 事务边界在 service（commit 由 service 管）
- DTO 与 ORM 转换由 schema 完成（to_orm / apply_to）

业务规则（v4）：
- type 必须是 CONDITION / TRANSFORM（schema 层已校验，此处再做防御性校验）
- CONDITION：value 必须为空字符串（分数不在 attribute 上，而在 rule.score）
- TRANSFORM：value 必须只包含数学运算符和 input 变量（防止代码注入）
- TRANSFORM：input_min / input_max 半开半闭，min < max
- 同一 group_code 的所有 attribute 必须共享同一 group_name（创建时若 group_code 已存在，强制覆盖 group_name）
- 删除 attribute 不影响历史 application（application 不直接引用 attribute）
"""
import logging
import re
from decimal import Decimal
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.template import Attribute, AttributeType
from src.app.schemas.template import (
    AttributeCreateRequest,
    AttributeUpdateRequest,
)
from src.app.schemas.errors import (
    NotFoundError,
    BadRequestError,
    ConflictError,
)
from src.repositories.attribute_repo import AttributeRepository

logger = logging.getLogger(__name__)


# ============================================================
# 业务校验（与 schema 层 Pydantic 校验的差异：schema 防输入格式，service 防业务语义）
# ============================================================

# TRANSFORM 公式白名单字符：0-9 数字 + - * / ** ( ) . 空格 + input 变量
# 注意：simpleeval 自身会做安全求值；这里再加一层白名单减少攻击面
_FORMULA_PATTERN = re.compile(r"^[0-9+\-*/().\s*]*$")


def _validate_formula(value: str) -> None:
    """校验 TRANSFORM 公式格式（白名单字符）"""
    if not value or not value.strip():
        raise BadRequestError("TRANSFORM 公式不能为空")
    # 先过白名单字符
    stripped = value.replace("input", "").strip()
    if not stripped:
        # value 就是 "input"（一个变量也算合法）
        return
    if not _FORMULA_PATTERN.match(stripped):
        raise BadRequestError(
            f"TRANSFORM 公式仅允许数字、+-*/()、. 字符与 input 变量，当前值: {value!r}"
        )


def _validate_interval(
    input_min: Optional[Decimal],
    input_max: Optional[Decimal],
) -> None:
    """校验半开半闭区间 [min, max)"""
    if input_min is not None and input_min < 0:
        raise BadRequestError(f"input_min 必须 >= 0，当前值: {input_min}")
    if input_min is not None and input_max is not None and input_min >= input_max:
        raise BadRequestError(
            f"半开半闭区间要求 input_min < input_max，当前: min={input_min}, max={input_max}"
        )


# ============================================================
# 服务实现
# ============================================================

class AttributeService:
    """Attribute 服务（v4）"""

    @staticmethod
    def validate(req: AttributeCreateRequest) -> None:
        """业务校验（DTO 层 Pydantic 校验输入格式，本方法校验业务语义）。

        注：group_name 一致性由 create() 在事务内强制覆盖旧值，本方法不重复校验。
        """
        attr_type = req.type

        if attr_type == AttributeType.CONDITION.value:
            # CONDITION：value 必须为空字符串（schema 的 default 已设置为 ""，但仍防御性校验）
            if req.value and req.value.strip():
                raise BadRequestError(
                    "CONDITION 类型 attribute 的 value 必须为空字符串（分数下沉到 rule.score）"
                )
        elif attr_type == AttributeType.TRANSFORM.value:
            # TRANSFORM：value 必须非空、必须是合法公式
            _validate_formula(req.value)
            _validate_interval(req.inputMin, req.inputMax)
        else:
            # schema 层已经校验过，这里只是兜底
            raise BadRequestError(f"type 必须是 CONDITION / TRANSFORM，当前值: {attr_type}")

    # ---------- 读 ----------

    @staticmethod
    async def list_paged(
        db: AsyncSession,
        *,
        is_active: Optional[bool] = True,
        attr_type: Optional[str] = None,
        group_code: Optional[str] = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> tuple[List[Attribute], int]:
        """分页列表 + 总数。"""
        total = await AttributeRepository.count(
            db,
            is_active=is_active,
            attr_type=attr_type,
            group_code=group_code,
        )
        attributes = await AttributeRepository.list_paged(
            db,
            is_active=is_active,
            attr_type=attr_type,
            group_code=group_code,
            offset=(page_num - 1) * page_size,
            limit=page_size,
        )
        return attributes, total

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        attribute_id: int,
    ) -> Attribute:
        attribute = await AttributeRepository.get_by_id(db, attribute_id)
        if attribute is None:
            raise NotFoundError(f"属性(id={attribute_id})不存在")
        return attribute

    @staticmethod
    async def list_by_rule(
        db: AsyncSession,
        rule_id: int,
    ) -> List[Attribute]:
        """rule 已绑 attribute 列表。"""
        return await AttributeRepository.list_by_rule_id(db, rule_id)

    # ---------- 写 ----------

    @staticmethod
    async def create(
        db: AsyncSession,
        req: AttributeCreateRequest,
    ) -> Attribute:
        """创建 attribute。

        业务规则：
        - 同 group_code 的所有 attribute 必须共享 group_name（创建时若 group_code 已存在，强制覆盖 group_name）
        - 公式 / 区间校验
        """
        # 业务校验（防御性二次校验，schema 已校验过）
        AttributeService.validate(req)

        # 同 group_name 一致性：若 group_code 已存在，强制覆盖 group_name
        existing = await AttributeRepository.get_by_group_code(db, req.groupCode)
        if existing is not None:
            if existing.group_name != req.groupName:
                logger.info(
                    "attribute.group_code=%s 的 group_name 已自动覆盖: %s -> %s",
                    req.groupCode, existing.group_name, req.groupName,
                )
                req = req.model_copy(update={"groupName": existing.group_name})

        attribute = req.to_orm()
        db.add(attribute)
        await AttributeRepository.commit(db)
        await AttributeRepository.refresh(db, attribute)
        return attribute

    @staticmethod
    async def update(
        db: AsyncSession,
        attribute_id: int,
        req: AttributeUpdateRequest,
    ) -> Attribute:
        """修改 attribute。"""
        attribute = await AttributeService.get_by_id(db, attribute_id)

        # 修改 type 时，重新校验 value / 区间
        if req.type is not None:
            # 合并"新值或原值"用于校验
            new_value = req.value if req.value is not None else (attribute.value or "")
            new_min = req.inputMin if req.inputMin is not None else attribute.input_min
            new_max = req.inputMax if req.inputMax is not None else attribute.input_max
            new_type = req.type

            if new_type == AttributeType.CONDITION.value:
                if new_value and new_value.strip():
                    raise BadRequestError(
                        "CONDITION 类型 attribute 的 value 必须为空字符串"
                    )
            elif new_type == AttributeType.TRANSFORM.value:
                _validate_formula(new_value)
                _validate_interval(new_min, new_max)

        modified = req.apply_to(attribute)
        if modified:
            await AttributeRepository.commit(db)
            await AttributeRepository.refresh(db, attribute)
        return attribute

    @staticmethod
    async def delete(
        db: AsyncSession,
        attribute_id: int,
    ) -> None:
        """删除 attribute。

        - 不影响已有 application（application 不直接引用 attribute）
        - FK CASCADE 自动清理 rule_attribute 行
        """
        await AttributeService.get_by_id(db, attribute_id)  # 校验存在
        await AttributeRepository.delete(db, attribute_id)
        await AttributeRepository.commit(db)


__all__ = ["AttributeService"]