"""证明材料服务"""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from datetime import datetime

from src.models import Application, ApplicationProof, User
from src.app.schemas.errors import NotFoundError, BadRequestError, ConflictError, ForbiddenError


class ProofService:
    """证明材料管理服务"""

    @staticmethod
    async def get_by_application(
        db: AsyncSession,
        application_id: int,
        user_id: Optional[int] = None,
    ) -> Optional[List[ApplicationProof]]:
        """获取申请的证明材料"""
        if user_id:
            app = await db.execute(
                select(Application).where(Application.id == application_id)
            )
            application = app.scalar_one_or_none()
            if not application or application.user_id != user_id:
                return None  # 无权访问

        result = await db.execute(
            select(ApplicationProof)
            .where(ApplicationProof.application_id == application_id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        proof_id: int,
    ) -> Optional[ApplicationProof]:
        """根据ID获取证明材料"""
        result = await db.execute(
            select(ApplicationProof).where(ApplicationProof.id == proof_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def approve(
        db: AsyncSession,
        proof_id: int,
        reviewer_id: int,
        comment: Optional[str] = None,
    ) -> Optional[ApplicationProof]:
        """审核证明材料通过"""
        proof = await ProofService.get_by_id(db, proof_id)
        if not proof:
            return None
        if proof.status == 1:
            raise ConflictError("该证明材料已通过审核")

        # 更新审核记录
        reviewer_ids = proof.reviewer_ids or []
        if reviewer_id not in reviewer_ids:
            reviewer_ids.append(reviewer_id)

        review_records = proof.review_records or []
        review_records.append({
            "reviewerId": reviewer_id,
            "action": "approve",
            "comment": comment or "",
            "time": datetime.utcnow().isoformat(),
        })

        proof.approved_count = (proof.approved_count or 0) + 1
        proof.reviewer_ids = reviewer_ids
        proof.review_records = review_records

        if proof.approved_count >= proof.review_count:
            proof.status = 1

        await db.commit()
        await db.refresh(proof)
        return proof

    @staticmethod
    async def reject(
        db: AsyncSession,
        proof_id: int,
        reviewer_id: int,
        comment: Optional[str] = None,
    ) -> Optional[ApplicationProof]:
        """审核证明材料驳回"""
        proof = await ProofService.get_by_id(db, proof_id)
        if not proof:
            return None
        if proof.status != 0:
            raise ConflictError("该证明材料已被审核")

        reviewer_ids = proof.reviewer_ids or []
        if reviewer_id not in reviewer_ids:
            reviewer_ids.append(reviewer_id)

        review_records = proof.review_records or []
        review_records.append({
            "reviewerId": reviewer_id,
            "action": "reject",
            "comment": comment or "",
            "time": datetime.utcnow().isoformat(),
        })

        proof.reviewer_ids = reviewer_ids
        proof.review_records = review_records
        proof.status = 2

        await db.commit()
        await db.refresh(proof)
        return proof

    @staticmethod
    async def add(
        db: AsyncSession,
        application_id: int,
        user_id: int,
        file_id: int,
        proof_value: float = 0,
        remark: Optional[str] = None,
        review_count: Optional[int] = None,
    ) -> Optional[ApplicationProof]:
        """追加证明材料"""
        app = await db.execute(
            select(Application).where(Application.id == application_id)
        )
        application = app.scalar_one_or_none()
        if not application:
            raise NotFoundError(f"申请不存在: id={application_id}")
        if application.user_id != user_id:
            raise ForbiddenError("无权操作此申请")
        if application.status != 0:
            raise ConflictError("只能在待审核状态下追加证明材料")

        proof = ApplicationProof(
            application_id=application_id,
            proof_file_id=file_id,
            proof_value=proof_value,
            review_count=review_count or application.review_count,
            remark=remark,
            status=0,
        )
        db.add(proof)
        await db.commit()
        await db.refresh(proof)
        return proof

    @staticmethod
    async def resubmit(
        db: AsyncSession,
        proof_id: int,
        user_id: int,
        file_id: Optional[int] = None,
        proof_value: Optional[float] = None,
        remark: Optional[str] = None,
    ) -> Optional[ApplicationProof]:
        """重新提交被驳回的证明材料"""
        proof = await ProofService.get_by_id(db, proof_id)
        if not proof:
            return None

        app = await db.execute(
            select(Application).where(Application.id == proof.application_id)
        )
        application = app.scalar_one_or_none()
        if not application or application.user_id != user_id:
            raise ForbiddenError("无权操作此证明材料")
        if proof.status != 2:
            raise ConflictError("只能重新提交已驳回的证明材料")

        if file_id:
            proof.proof_file_id = file_id
        if proof_value is not None:
            proof.proof_value = proof_value
        if remark:
            proof.remark = remark
        # 重置状态为待审核
        proof.status = 0
        proof.approved_count = 0
        proof.reviewer_ids = []
        proof.review_records = []

        await db.commit()
        await db.refresh(proof)
        return proof

    @staticmethod
    async def override_status(
        db: AsyncSession,
        proof_id: int,
        reviewer_id: int,
        status: int,
        comment: Optional[str] = None,
    ) -> Optional[ApplicationProof]:
        """审核员覆盖修改状态"""
        if status not in [1, 2]:
            raise BadRequestError("status 只能为 1（通过）或 2（驳回）")

        proof = await ProofService.get_by_id(db, proof_id)
        if not proof:
            return None

        review_records = proof.review_records or []
        review_records.append({
            "reviewerId": reviewer_id,
            "action": "override_approve" if status == 1 else "override_reject",
            "comment": comment or "",
            "time": datetime.utcnow().isoformat(),
        })

        proof.status = status
        proof.approved_count = status == 1 and proof.review_count or 0
        proof.review_records = review_records

        await db.commit()
        await db.refresh(proof)
        return proof


def get_proof_status_text(status: int) -> str:
    """获取证明材料状态文本"""
    return {0: "待审核", 1: "已通过", 2: "已驳回"}.get(status, "未知")
