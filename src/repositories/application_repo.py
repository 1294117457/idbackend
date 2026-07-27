"""Application 数据访问层（聚合根）

职责：只做"读 / 写 ORM"，没有业务规则。
包含 Application、ApplicationProof、ApplicationOperation 三个表的操作。
"""
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy import select, update, delete, func, and_, literal_column, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import Application, ApplicationProof, ApplicationOperation, ApplicationStatus, ProofStatus
from src.app.schemas import ApplicationQueryRequest


class ApplicationRepository:
    """application 表的数据访问层（聚合根）"""

    # =========================================================================
    # Application 读操作
    # =========================================================================

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        application_id: int,
        for_update: bool = False,
    ) -> Optional[Application]:
        """按 ID 查询（可选加行锁）"""
        stmt = select(Application).where(Application.id == application_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_with_details(
        db: AsyncSession,
        application_id: int,
        for_update: bool = False,
    ) -> Optional[Application]:
        """按 ID 查询（预加载 proofs + user）"""
        stmt = (
            select(Application)
            .where(Application.id == application_id)
            .options(
                selectinload(Application.proofs),
                selectinload(Application.user),
            )
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_with_details_by_id(
        db: AsyncSession,
        application_id: int,
    ) -> Optional[Application]:
        """获取详情（预加载 proofs + user）"""
        stmt = (
            select(Application)
            .where(Application.id == application_id)
            .options(
                selectinload(Application.proofs),
                selectinload(Application.user),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_by_user(
        db: AsyncSession,
        user_id: int,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> Tuple[List[Application], int]:
        """用户自己的申请列表"""
        conditions = [Application.user_id == user_id]
        if status:
            conditions.append(Application.status == status)

        base_filter = select(Application.id).where(*conditions).subquery()
        count_q = select(func.count()).select_from(base_filter)
        total = (await db.execute(count_q)).scalar() or 0

        query = (
            select(Application)
            .where(*conditions)
            .options(selectinload(Application.proofs), selectinload(Application.user))
            .order_by(Application.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await db.execute(query)
        return list(result.scalars().all()), total

    @staticmethod
    async def check_user_template_duplicate(
        db: AsyncSession,
        user_id: int,
        template_id: int,
        exclude_application_id: Optional[int] = None,
    ) -> Optional[Application]:
        """检查某学生对某模板是否有未取消的申请（用于重复提交校验）。

        edit_submit 场景需传入 exclude_application_id 排除自身。
        """
        conditions = [
            Application.user_id == user_id,
            Application.template_id == template_id,
            Application.status.notin_(
                [ApplicationStatus.CANCELLED.value, ApplicationStatus.REVOKED.value]
            ),
        ]
        if exclude_application_id is not None:
            conditions.append(Application.id != exclude_application_id)
        result = await db.execute(
            select(Application)
            .where(*conditions)
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_pending_for_reviewer(
        db: AsyncSession,
        req: ApplicationQueryRequest,
    ) -> Tuple[List[Application], int]:
        """管理员的待审核列表（status=APPLYING，所有管理员可见）"""
        conditions = [
            Application.status == ApplicationStatus.APPLYING.value,
        ]

        from sqlalchemy.orm import aliased
        from src.models.user import User
        user_alias = aliased(User)

        if req.fullName:
            conditions.append(user_alias.full_name.ilike(f"%{req.fullName}%"))
        if req.studentId:
            conditions.append(user_alias.username.ilike(f"{req.studentId}%"))
        if req.templateName:
            conditions.append(Application.template_name.ilike(f"%{req.templateName}%"))
        if req.startTime:
            from datetime import datetime, timezone
            start = datetime.fromisoformat(req.startTime.replace(" ", "T"))
            if start.tzinfo:
                start = start.astimezone(timezone.utc).replace(tzinfo=None)
            conditions.append(Application.created_at >= start)
        if req.endTime:
            from datetime import datetime, timezone
            end = datetime.fromisoformat(req.endTime.replace(" ", "T"))
            if end.tzinfo:
                end = end.astimezone(timezone.utc).replace(tzinfo=None)
            conditions.append(Application.created_at <= end)

        base_filter = (
            select(Application.id)
            .join(user_alias, Application.user_id == user_alias.id)
            .where(*conditions)
            .subquery()
        )
        count_q = select(func.count()).select_from(base_filter)
        total = (await db.execute(count_q)).scalar() or 0

        query = (
            select(Application)
            .join(user_alias, Application.user_id == user_alias.id)
            .where(*conditions)
            .options(
                selectinload(Application.proofs),
                selectinload(Application.user),
            )
            .order_by(Application.created_at.desc())
            .offset((req.pageNum - 1) * req.pageSize)
            .limit(req.pageSize)
        )
        result = await db.execute(query)
        return list(result.scalars().all()), total

    @staticmethod
    async def list_reviewed_by_reviewer(
        db: AsyncSession,
        req: ApplicationQueryRequest,
    ) -> Tuple[List[Application], int]:
        """管理员的审核历史列表（不限制审核人，可查看全部审核记录）"""
        conditions = []

        from sqlalchemy.orm import aliased
        from src.models.user import User
        user_alias = aliased(User)

        if req.fullName:
            conditions.append(user_alias.full_name.ilike(f"%{req.fullName}%"))
        if req.studentId:
            conditions.append(user_alias.username.ilike(f"{req.studentId}%"))
        if req.templateName:
            conditions.append(Application.template_name.ilike(f"%{req.templateName}%"))
        if req.status:
            conditions.append(Application.status == req.status)
        else:
            # 默认只显示已审核完成的申请（PASSED/REJECTED/REVOKED/CANCELLED）
            conditions.append(Application.status.in_(['PASSED', 'REJECTED', 'REVOKED', 'CANCELLED']))
        if req.startTime:
            from datetime import datetime, timezone
            start = datetime.fromisoformat(req.startTime.replace(" ", "T"))
            if start.tzinfo:
                start = start.astimezone(timezone.utc).replace(tzinfo=None)
            conditions.append(Application.updated_at >= start)
        if req.endTime:
            from datetime import datetime, timezone
            end = datetime.fromisoformat(req.endTime.replace(" ", "T"))
            if end.tzinfo:
                end = end.astimezone(timezone.utc).replace(tzinfo=None)
            conditions.append(Application.updated_at <= end)

        base_filter = (
            select(Application.id)
            .join(user_alias, Application.user_id == user_alias.id)
            .where(*conditions)
            .subquery()
        )
        count_q = select(func.count()).select_from(base_filter)
        total = (await db.execute(count_q)).scalar() or 0

        query = (
            select(Application)
            .join(user_alias, Application.user_id == user_alias.id)
            .where(*conditions)
            .options(
                selectinload(Application.proofs),
                selectinload(Application.user),
            )
            .order_by(Application.updated_at.desc())
            .offset((req.pageNum - 1) * req.pageSize)
            .limit(req.pageSize)
        )
        result = await db.execute(query)
        return list(result.scalars().all()), total

    @staticmethod
    async def list_admin_all(
        db: AsyncSession,
        req: ApplicationQueryRequest,
    ) -> Tuple[List[Application], int]:
        """管理员查询所有申请"""
        conditions = []
        if req.status:
            conditions.append(Application.status == req.status)
        if req.templateName:
            conditions.append(Application.template_name.ilike(f"%{req.templateName}%"))

        base_filter = select(Application.id).where(*conditions).subquery()
        count_q = select(func.count()).select_from(base_filter)
        total = (await db.execute(count_q)).scalar() or 0

        query = (
            select(Application)
            .where(*conditions)
            .options(selectinload(Application.proofs), selectinload(Application.user))
            .order_by(Application.created_at.desc())
            .offset((req.pageNum - 1) * req.pageSize)
            .limit(req.pageSize)
        )
        result = await db.execute(query)
        return list(result.scalars().all()), total

    # =========================================================================
    # ApplicationProof 读操作
    # =========================================================================

    @staticmethod
    async def list_proofs_by_application(
        db: AsyncSession,
        application_id: int,
    ) -> List[ApplicationProof]:
        """查询某申请的所有 proof"""
        stmt = select(ApplicationProof).where(
            ApplicationProof.application_id == application_id
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_proof_by_id(
        db: AsyncSession,
        proof_id: int,
    ) -> Optional[ApplicationProof]:
        """按 ID 查询 proof"""
        return await db.get(ApplicationProof, proof_id)

    @staticmethod
    async def count_pending_or_rejected_proofs(
        db: AsyncSession,
        application_id: int,
    ) -> int:
        """统计某申请下状态为 PENDING 或 REJECTED 的 proof 数量"""
        result = await db.execute(
            select(func.count())
            .select_from(ApplicationProof)
            .where(
                and_(
                    ApplicationProof.application_id == application_id,
                    ApplicationProof.status.in_([
                        ProofStatus.PENDING.value,
                        ProofStatus.REJECTED.value,
                    ]),
                )
            )
        )
        return result.scalar() or 0

    # =========================================================================
    # ApplicationOperation 读操作
    # =========================================================================

    @staticmethod
    async def list_operations_by_application(
        db: AsyncSession,
        application_id: int,
    ) -> List[ApplicationOperation]:
        """查询某申请的所有操作记录"""
        stmt = (
            select(ApplicationOperation)
            .where(ApplicationOperation.application_id == application_id)
            .order_by(ApplicationOperation.created_at.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # =========================================================================
    # ApplicationProof 写操作
    # =========================================================================

    @staticmethod
    async def insert_proof(
        db: AsyncSession,
        proof: ApplicationProof,
    ) -> ApplicationProof:
        """新增 proof"""
        db.add(proof)
        await db.flush()
        return proof

    @staticmethod
    async def insert_proofs_many(
        db: AsyncSession,
        proofs: List[ApplicationProof],
    ) -> None:
        """批量新增 proofs"""
        for proof in proofs:
            db.add(proof)
        await db.flush()

    @staticmethod
    async def update_proof(
        db: AsyncSession,
        proof: ApplicationProof,
    ) -> ApplicationProof:
        """更新 proof（已有对象，直接修改后 flush）"""
        await db.flush()
        return proof

    @staticmethod
    async def delete_proof(
        db: AsyncSession,
        proof: ApplicationProof,
    ) -> None:
        """删除 proof"""
        await db.delete(proof)
        await db.flush()

    @staticmethod
    async def delete_proof_by_id(
        db: AsyncSession,
        proof_id: int,
    ) -> int:
        """按 ID 删除 proof"""
        proof = await db.get(ApplicationProof, proof_id)
        if proof:
            await db.delete(proof)
            await db.flush()
        return 1 if proof else 0

    # =========================================================================
    # ApplicationOperation 写操作
    # =========================================================================

    @staticmethod
    async def insert_operation(
        db: AsyncSession,
        operation: ApplicationOperation,
    ) -> ApplicationOperation:
        """新增操作记录"""
        db.add(operation)
        await db.flush()
        return operation

    # =========================================================================
    # Application 写操作
    # =========================================================================

    @staticmethod
    async def insert(
        db: AsyncSession,
        application: Application,
    ) -> Application:
        """新增 application"""
        db.add(application)
        await db.flush()
        return application


__all__ = ["ApplicationRepository"]
