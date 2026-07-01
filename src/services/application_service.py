"""加分申请服务"""
from sqlalchemy import select, and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from datetime import datetime

from src.models import (
    Application,
    ApplicationProof,
    User,
    FileMetadata,
)


class ApplicationStatus:
    PENDING = 0
    APPROVED = 1
    REJECTED = 2
    CANCELLED = 3
    REVOKED = 4


class ApplicationService:
    """加分申请服务"""

    @staticmethod
    async def create_application(
        db: AsyncSession,
        user_id: int,
        template_id: int,
        template_name: str,
        apply_score: float,
        rule_id: Optional[int] = None,
        apply_input: Optional[float] = None,
        score_type: int = 0,
    ) -> Application:
        """创建申请"""
        # 获取用户信息
        user_result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()

        application = Application(
            user_id=user_id,
            student_id=user.student_id if user else "",
            student_name=user.full_name if user else "",
            major=user.major if user else "",
            enrollment_year=user.grade if user else None,
            template_name=template_name,
            score_type=score_type,
            apply_score=apply_score,
            rule_id=rule_id,
            apply_input=apply_input,
            status=ApplicationStatus.PENDING.value,
        )

        db.add(application)
        await db.commit()
        await db.refresh(application)
        return application

    @staticmethod
    async def add_proof(
        db: AsyncSession,
        application_id: int,
        file_id: int,
        proof_value: float = 0,
    ) -> ApplicationProof:
        """添加证明材料"""
        proof = ApplicationProof(
            application_id=application_id,
            proof_file_id=file_id,
            proof_value=proof_value,
            status=ApplicationStatus.PENDING.value,
        )
        db.add(proof)
        await db.commit()
        await db.refresh(proof)
        return proof

    @staticmethod
    async def get_application_by_id(
        db: AsyncSession,
        application_id: int,
    ) -> Optional[Application]:
        """根据ID获取申请"""
        result = await db.execute(
            select(Application).where(Application.id == application_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_applications(
        db: AsyncSession,
        user_id: int,
        status: Optional[int] = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[List[Application], int]:
        """获取用户的申请列表"""
        query = select(Application).where(Application.user_id == user_id)

        if status is not None:
            query = query.where(Application.status == status)

        # 获取总数
        from sqlalchemy import func

        count_result = await db.execute(
            select(func.count()).where(Application.user_id == user_id)
        )
        total = count_result.scalar()

        # 分页
        query = query.order_by(Application.created_at.desc())
        query = query.offset((page - 1) * size).limit(size)

        result = await db.execute(query)
        applications = result.scalars().all()

        return list(applications), total

    @staticmethod
    async def get_pending_applications(
        db: AsyncSession,
        page: int = 1,
        size: int = 20,
    ) -> tuple[List[Application], int]:
        """获取待审核的申请"""
        query = select(Application).where(
            Application.status == ApplicationStatus.PENDING.value
        )

        # 获取总数
        from sqlalchemy import func

        count_result = await db.execute(
            select(func.count()).where(
                Application.status == ApplicationStatus.PENDING.value
            )
        )
        total = count_result.scalar()

        # 分页
        query = query.order_by(Application.created_at.desc())
        query = query.offset((page - 1) * size).limit(size)

        result = await db.execute(query)
        applications = result.scalars().all()

        return list(applications), total

    @staticmethod
    async def approve_application(
        db: AsyncSession,
        application_id: int,
        reviewer_id: int,
        comment: Optional[str] = None,
    ) -> Optional[Application]:
        """审核通过"""
        application = await ApplicationService.get_application_by_id(
            db, application_id
        )
        if not application:
            return None

        # 更新审核记录
        reviewer_ids = application.reviewer_ids or []
        if reviewer_id not in reviewer_ids:
            reviewer_ids.append(reviewer_id)

        review_records = application.review_records or []
        review_records.append({
            "reviewerId": reviewer_id,
            "action": "approve",
            "comment": comment,
            "time": datetime.utcnow().isoformat(),
        })

        application.reviewer_ids = reviewer_ids
        application.review_records = review_records
        application.current_review_count = len(reviewer_ids)

        # 检查是否全部审核通过
        if application.current_review_count >= application.review_count:
            application.status = ApplicationStatus.APPROVED.value
            # 更新用户积分
            await ApplicationService._update_user_score(
                db, application.user_id, application.gain_score or application.apply_score
            )

        await db.commit()
        await db.refresh(application)
        return application

    @staticmethod
    async def reject_application(
        db: AsyncSession,
        application_id: int,
        reviewer_id: int,
        comment: Optional[str] = None,
    ) -> Optional[Application]:
        """审核驳回"""
        application = await ApplicationService.get_application_by_id(
            db, application_id
        )
        if not application:
            return None

        # 更新审核记录
        reviewer_ids = application.reviewer_ids or []
        if reviewer_id not in reviewer_ids:
            reviewer_ids.append(reviewer_id)

        review_records = application.review_records or []
        review_records.append({
            "reviewerId": reviewer_id,
            "action": "reject",
            "comment": comment,
            "time": datetime.utcnow().isoformat(),
        })

        application.reviewer_ids = reviewer_ids
        application.review_records = review_records
        application.status = ApplicationStatus.REJECTED.value

        await db.commit()
        await db.refresh(application)
        return application

    @staticmethod
    async def _update_user_score(
        db: AsyncSession,
        user_id: int,
        score: float,
    ) -> None:
        """更新用户学业成绩"""
        user_result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()
        if user:
            user.academic_score = (user.academic_score or 0) + score
            await db.commit()

    @staticmethod
    async def cancel_application(
        db: AsyncSession,
        application_id: int,
        user_id: int,
    ) -> bool:
        """取消申请 (只能取消待审核的)"""
        application = await ApplicationService.get_application_by_id(
            db, application_id
        )
        if not application or application.user_id != user_id:
            return False

        if application.status != ApplicationStatus.PENDING.value:
            return False

        await db.delete(application)
        await db.commit()
        return True

    @staticmethod
    async def resubmit_application(
        db: AsyncSession,
        application_id: int,
        user_id: int,
    ) -> Optional[Application]:
        """重新提交已驳回的申请"""
        application = await ApplicationService.get_application_by_id(
            db, application_id
        )
        if not application or application.user_id != user_id:
            return None

        if application.status != ApplicationStatus.REJECTED.value:
            return None

        application.status = ApplicationStatus.PENDING.value
        application.reviewer_ids = []
        application.review_records = []
        application.current_review_count = 0

        await db.commit()
        await db.refresh(application)
        return application

    @staticmethod
    async def get_pending_applications_paged(
        db: AsyncSession,
        page: int = 1,
        size: int = 20,
        student_id: Optional[str] = None,
        student_name: Optional[str] = None,
        major: Optional[str] = None,
    ) -> tuple[List[Application], int]:
        """分页获取待审核申请"""
        query = select(Application).where(
            Application.status == ApplicationStatus.PENDING.value
        )

        # 筛选条件
        if student_id:
            query = query.where(Application.student_id.like(f"%{student_id}%"))
        if student_name:
            query = query.where(Application.student_name.like(f"%{student_name}%"))
        if major:
            query = query.where(Application.major.like(f"%{major}%"))

        # 获取总数
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await db.execute(count_query)
        total = count_result.scalar() or 0

        # 分页
        query = query.order_by(Application.created_at.desc())
        query = query.offset((page - 1) * size).limit(size)

        result = await db.execute(query)
        return list(result.scalars().all()), total

    @staticmethod
    async def get_audit_history_paged(
        db: AsyncSession,
        page: int = 1,
        size: int = 20,
        student_id: Optional[str] = None,
        student_name: Optional[str] = None,
        major: Optional[str] = None,
    ) -> tuple[List[Application], int]:
        """分页获取审核历史（已审核的）"""
        query = select(Application).where(
            Application.status.in_([ApplicationStatus.APPROVED.value, ApplicationStatus.REJECTED.value, ApplicationStatus.REVOKED.value])
        )

        # 筛选条件
        if student_id:
            query = query.where(Application.student_id.like(f"%{student_id}%"))
        if student_name:
            query = query.where(Application.student_name.like(f"%{student_name}%"))
        if major:
            query = query.where(Application.major.like(f"%{major}%"))

        # 获取总数
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await db.execute(count_query)
        total = count_result.scalar() or 0

        # 分页
        query = query.order_by(Application.created_at.desc())
        query = query.offset((page - 1) * size).limit(size)

        result = await db.execute(query)
        return list(result.scalars().all()), total

    @staticmethod
    async def revoke_application(
        db: AsyncSession,
        application_id: int,
        reviewer_id: int,
        reason: str,
    ) -> bool:
        """撤销已通过的申请"""
        application = await ApplicationService.get_application_by_id(db, application_id)
        if not application:
            return False

        if application.status != ApplicationStatus.APPROVED.value:
            return False

        # 扣减用户积分
        gain_score = application.gain_score or application.apply_score or 0
        await ApplicationService._deduct_user_score(db, application.user_id, gain_score)

        # 更新状态
        application.status = ApplicationStatus.REVOKED.value

        # 记录撤销原因
        review_records = application.review_records or []
        review_records.append({
            "reviewerId": reviewer_id,
            "action": "revoked",
            "comment": reason,
            "time": datetime.utcnow().isoformat(),
        })
        application.review_records = review_records

        await db.commit()
        return True

    @staticmethod
    async def _deduct_user_score(
        db: AsyncSession,
        user_id: int,
        score: float,
    ) -> None:
        """扣减用户学业成绩"""
        user_result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()
        if user:
            user.academic_score = max(0, (user.academic_score or 0) - score)
            await db.commit()
