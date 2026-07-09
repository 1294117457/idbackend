"""ExtraInfoField 服务（业务编排层）

设计原则：
- 业务规则全部在此
- 抛通用业务异常（NotFoundError / BadRequestError），由全局 exception_handler 翻译为 HTTP 响应
- 事务边界在 service
- DTO 与 ORM 的转换由 schema 完成
"""
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.extra_info_field import ExtraInfoField
from src.app.schemas.extra_info_field import (
    ExtraInfoFieldCreateRequest,
    ExtraInfoFieldUpdateRequest,
    ExtraInfoFieldVO,
    ExtraInfoFieldListVO,
    FIELD_TYPES,
)
from src.app.schemas.errors import NotFoundError, BadRequestError
from src.repositories.extra_info_field_repo import ExtraInfoFieldRepository


# ===================== 允许的类型列表 =====================

ALLOWED_TYPES: set = {"TEXT", "NUMBER", "SELECT", "DATE"}


# ===================== 服务实现 =====================

class ExtraInfoFieldService:

    # ---------- 读接口 ----------

    @staticmethod
    async def list_all(
        db: AsyncSession,
        *,
        include_inactive: bool = False,
    ) -> List[ExtraInfoField]:
        """获取所有字段（平铺）。"""
        return await ExtraInfoFieldRepository.list_all(db, include_inactive=include_inactive)

    @staticmethod
    async def page(
        db: AsyncSession,
        req,
    ) -> ExtraInfoFieldListVO:
        """分页列表 VO。"""
        fields = await ExtraInfoFieldRepository.list_all(db, include_inactive=req.includeInactive)
        total = len(fields)
        start = (req.pageNum - 1) * req.pageSize
        end = start + req.pageSize
        items = [
            ExtraInfoFieldVO.from_orm_to_vo(f).model_dump()
            for f in fields[start:end]
        ]
        from src.app.schemas.page import Page
        return Page.from_list_to_page(
            items=items,
            total=total,
            page_num=req.pageNum,
            page_size=req.pageSize,
        )

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        field_id: int,
    ) -> ExtraInfoField:
        field = await ExtraInfoFieldRepository.get_by_id(db, field_id)
        if field is None:
            raise NotFoundError(f"字段(id={field_id})不存在")
        return field

    # ---------- 写接口 ----------

    @staticmethod
    async def create(
        db: AsyncSession,
        req: ExtraInfoFieldCreateRequest,
    ) -> ExtraInfoField:
        """创建字段。"""
        _validate_type(req.type)

        if req.type == "SELECT" and not req.options:
            raise BadRequestError("type=SELECT 时，options 不能为空")

        orm = req.to_orm()
        db.add(orm)
        await ExtraInfoFieldRepository.commit(db)
        await ExtraInfoFieldRepository.refresh(db, orm)
        return orm

    @staticmethod
    async def update(
        db: AsyncSession,
        field_id: int,
        req: ExtraInfoFieldUpdateRequest,
    ) -> ExtraInfoField:
        """修改字段。"""
        if req.is_empty():
            return await ExtraInfoFieldService.get_by_id(db, field_id)

        field = await ExtraInfoFieldRepository.get_by_id(db, field_id)
        if field is None:
            raise NotFoundError(f"字段(id={field_id})不存在")

        if req.type is not None:
            _validate_type(req.type)

        # 计算最终 options（type 改变时需重置）
        final_options = req.options
        if req.type == "SELECT":
            if req.options is None and field.type != "SELECT":
                raise BadRequestError("type=SELECT 时，options 不能为空")
        elif final_options is None:
            final_options = []

        if final_options is not None:
            req.options = final_options

        modified = req.apply_to(field)
        if modified:
            await ExtraInfoFieldRepository.commit(db)
            await ExtraInfoFieldRepository.refresh(db, field)
        return field

    @staticmethod
    async def delete(
        db: AsyncSession,
        field_id: int,
    ) -> None:
        """删除字段（不清理 user.extra_info 残留）。"""
        field = await ExtraInfoFieldRepository.get_by_id(db, field_id)
        if field is None:
            raise NotFoundError(f"字段(id={field_id})不存在")

        await ExtraInfoFieldRepository.delete_by_id(db, field_id)
        await ExtraInfoFieldRepository.commit(db)


# ===================== 内部辅助 =====================

def _validate_type(type_str: str) -> None:
    if type_str not in ALLOWED_TYPES:
        raise BadRequestError(
            f"不支持的字段类型: {type_str}，允许的类型: {', '.join(sorted(ALLOWED_TYPES))}"
        )
