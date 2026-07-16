"""加分申请服务

职责：只做业务逻辑和编排，数据库操作委托给 Repository 层。
"""
from __future__ import annotations

from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Application,
    ApplicationProof,
    ApplicationOperation,
    ApplicationStatus,
    ProofStatus,
    User,
)
from src.app.schemas.errors import (
    NotFoundError, BadRequestError, ConflictError, ForbiddenError,
)
from src.app.schemas import (
    ApplicationPayload, ProofPayload,
    ApplicationQueryRequest, ApplicationListVO, ApplicationVO,
    PassResultVO, RejectResultVO, CancelResultVO,
    ApplicationDetailVO,
)
from src.repositories import ApplicationRepository
from src.services.score_data_service import ScoreDataService
from src.app.context import get_user_id as _get_user_id, get_username as _get_username


class ApplicationService:
    """加分申请服务（业务逻辑层）"""

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def get_current_user_id() -> int:
        """获取当前用户 ID（从 contextvar）"""
        user_id = _get_user_id()
        if not user_id:
            from src.app.schemas.errors import UnauthorizedError
            raise UnauthorizedError()
        return user_id

    @staticmethod
    async def get_user_full_name(db: AsyncSession, user_id: int) -> str:
        """获取用户全名（用于操作日志）"""
        user = await db.get(User, user_id)
        return (user.full_name if user else None) or (user.username if user else f"user#{user_id}")


    @staticmethod
    async def save_draft(
        db: AsyncSession,
        payload: ApplicationPayload,
        review_count: int = 1,
    ) -> ApplicationVO:
        """保存草稿（新建或更新 DRAFT）"""
        user_id = ApplicationService.get_current_user_id()
        user = await db.get(User, user_id)
        if not user:
            raise NotFoundError(f"用户(id={user_id})不存在")

        application_id = payload.applicationId

        if application_id is None:
            application = payload.to_application_model(
                user_id=user_id,
                status=ApplicationStatus.DRAFT.value,
                review_count=review_count,
            )
            await ApplicationRepository.insert(db, application)

            for proof in payload.build_proofs(application.id):
                await ApplicationRepository.insert_proof(db, proof)

            await ApplicationRepository.commit(db)
            await ApplicationRepository.refresh(db, application)
        else:
            application = await ApplicationRepository.get_with_details(db, application_id, for_update=True)

            if application.user_id != user_id:
                raise ForbiddenError("仅本人可编辑草稿")
            if application.status != ApplicationStatus.DRAFT.value:
                raise ConflictError(f"申请当前状态 {application.status}，仅 DRAFT 可编辑")

            payload.apply_to_model(application)

            await ApplicationService._replace_proofs(db, application.id, payload.proofList)
            await ApplicationRepository.commit(db)
            await ApplicationRepository.refresh(db, application)

        app_with_details = await ApplicationRepository.get_with_details_by_id(db, application.id)
        return ApplicationVO.from_orm_to_vo(app_with_details)

    @staticmethod
    async def submit(
        db: AsyncSession,
        payload: ApplicationPayload,
        review_count: int = 1,
    ) -> ApplicationVO:
        """新建并提交申请"""
        user_id = ApplicationService.get_current_user_id()
        if payload.applicationId is not None:
            raise BadRequestError("submit 接口 applicationId 必须为空")

        user = await db.get(User, user_id)
        if not user:
            raise NotFoundError(f"用户(id={user_id})不存在")

        operator_name = await ApplicationService.get_user_full_name(db, user_id)

        application = payload.to_application_model(
            user_id=user_id,
            status=ApplicationStatus.APPLYING.value,
            review_count=review_count,
        )
        await ApplicationRepository.insert(db, application)

        for proof in payload.build_proofs(application.id):
            await ApplicationRepository.insert_proof(db, proof)

        operation = ApplicationOperation(
            application_id=application.id,
            operator_id=user_id,
            operator_name=operator_name,
            operation=ApplicationStatus.APPLYING.value,
            remark=None,
        )
        await ApplicationRepository.insert_operation(db, operation)

        await ApplicationRepository.commit(db)
        await ApplicationRepository.refresh(db, application)

        app_with_details = await ApplicationRepository.get_with_details_by_id(db, application.id)
        return ApplicationVO.from_orm_to_vo(app_with_details)

    @staticmethod
    async def edit_submit(
        db: AsyncSession,
        payload: ApplicationPayload,
    ) -> ApplicationVO:
        """编辑后提交（仅 DRAFT/REJECTED/REVOKED 可操作）"""
        user_id = ApplicationService.get_current_user_id()
        if payload.applicationId is None:
            raise BadRequestError("edit-submit 接口 applicationId 不能为空")

        application = await ApplicationRepository.get_with_details(db, payload.applicationId, for_update=True)

        if application.user_id != user_id:
            raise ForbiddenError("仅本人可操作")
        if application.status not in (ApplicationStatus.DRAFT.value, ApplicationStatus.REJECTED.value, ApplicationStatus.REVOKED.value):
            raise ConflictError(f"申请当前状态 {application.status}，仅 DRAFT/REJECTED/REVOKED 可编辑提交")

        payload.apply_to_model(application, new_status=ApplicationStatus.APPLYING.value)
        application.approved_count = 0
        application.rejected_count = 0

        for proof in application.proofs:
            proof.status = ProofStatus.PENDING.value

        operator_name = await ApplicationService.get_user_full_name(db, user_id)
        operation = ApplicationOperation(
            application_id=application.id,
            operator_id=user_id,
            operator_name=operator_name,
            operation=ApplicationStatus.APPLYING.value,
            remark=None,
        )
        await ApplicationRepository.insert_operation(db, operation)

        await ApplicationRepository.commit(db)
        await ApplicationRepository.refresh(db, application)

        app_with_details = await ApplicationRepository.get_with_details_by_id(db, application.id)
        return ApplicationVO.from_orm_to_vo(app_with_details)

    @staticmethod
    async def cancel(
        db: AsyncSession,
        application_id: int,
        remark: Optional[str] = None,
    ) -> CancelResultVO:
        """取消申请"""
        user_id = ApplicationService.get_current_user_id()
        application = await ApplicationRepository.get_with_details(db, application_id, for_update=True)

        if application.user_id != user_id:
            raise ForbiddenError("仅本人可操作")
        if application.status not in (ApplicationStatus.DRAFT.value, ApplicationStatus.APPLYING.value):
            raise ConflictError(f"申请当前状态 {application.status}，仅 DRAFT 或 APPLYING 可取消")

        application.status = ApplicationStatus.CANCELLED.value

        operator_name = await ApplicationService.get_user_full_name(db, user_id)
        operation = ApplicationOperation(
            application_id=application.id,
            operator_id=user_id,
            operator_name=operator_name,
            operation=ApplicationStatus.CANCELLED.value,
            remark=remark,
        )
        await ApplicationRepository.insert_operation(db, operation)

        await ApplicationRepository.commit(db)
        await ApplicationRepository.refresh(db, application)
        return CancelResultVO.from_orm_to_vo(application)

    @staticmethod
    async def touch(
        db: AsyncSession,
        application_id: int,
    ) -> ApplicationVO:
        """DRAFT 状态下纯刷 updated_at"""
        user_id = ApplicationService.get_current_user_id()
        application = await ApplicationRepository.get_with_details(db, application_id)

        if application.user_id != user_id:
            raise ForbiddenError("仅本人可操作")
        if application.status != ApplicationStatus.DRAFT.value:
            raise ConflictError(f"申请当前状态 {application.status}，仅 DRAFT 可操作")

        await ApplicationRepository.commit(db)

        app_with_details = await ApplicationRepository.get_with_details_by_id(db, application.id)
        return ApplicationVO.from_orm_to_vo(app_with_details)

    # ------------------------------------------------------------------
    # 学生端：列表 / 详情
    # ------------------------------------------------------------------

    @staticmethod
    async def list_my_applications(
        db: AsyncSession,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> ApplicationListVO:
        """我的申请列表"""
        user_id = ApplicationService.get_current_user_id()
        applications, total = await ApplicationRepository.list_by_user(db, user_id, status, page, size)
        return ApplicationListVO.from_list_to_page(
            items=[ApplicationVO.from_orm_to_vo(a) for a in applications],
            total=total,
            page_num=page,
            page_size=size,
        )

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        application_id: int,
    ) -> Optional[Application]:
        """按 ID 查询"""
        return await ApplicationRepository.get_with_details_by_id(db, application_id)

    @staticmethod
    async def get_detail(
        db: AsyncSession,
        application_id: int,
    ) -> ApplicationDetailVO:
        """申请详情（含操作记录）"""
        application = await ApplicationRepository.get_with_details_by_id(db, application_id)
        if not application:
            raise NotFoundError(f"申请不存在")

        operations = await ApplicationRepository.list_operations_by_application(db, application_id)
        return ApplicationDetailVO.from_orm_to_vo(application, operations)

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    @staticmethod
    async def _replace_proofs(
        db: AsyncSession,
        application_id: int,
        proof_list: List[ProofPayload],
    ) -> None:
        """整表替换 proofs"""
        old_proofs = await ApplicationRepository.list_proofs_by_application(db, application_id)
        old_map: dict[int, ApplicationProof] = {p.id: p for p in old_proofs}

        payload_ids: set[int] = {pp.proofId for pp in proof_list if pp.proofId is not None}

        for old_id in (set(old_map) - payload_ids):
            await ApplicationRepository.delete_proof(db, old_map[old_id])

        for pp in proof_list:
            if pp.proofId is not None:
                old = old_map.get(pp.proofId)
                if old is None:
                    raise BadRequestError(f"proof(id={pp.proofId})不存在或不属于该申请")
                pp.apply_to_proof(old)
                await ApplicationRepository.update_proof(db, old)
            else:
                proof = pp.to_application_proof(application_id)
                await ApplicationRepository.insert_proof(db, proof)

    @staticmethod
    def _ensure_reviewer_id(application: Application, reviewer_id: int) -> None:
        """追加 reviewer_id（幂等）"""
        if application.reviewer_ids is None:
            application.reviewer_ids = []
        if reviewer_id not in application.reviewer_ids:
            application.reviewer_ids = application.reviewer_ids + [reviewer_id]

    # ------------------------------------------------------------------
    # 审核员端
    # ------------------------------------------------------------------

    @staticmethod
    async def review_proof(
        db: AsyncSession,
        application_id: int,
        proof_id: int,
        action: str,
        remark: Optional[str] = None,
    ) -> dict:
        """审核 proof（改 status）"""
        reviewer_id = ApplicationService.get_current_user_id()
        application = await ApplicationRepository.get_with_details(db, application_id, for_update=True)
        if not application:
            raise NotFoundError("申请不存在")
        if application.status != ApplicationStatus.APPLYING.value:
            raise ConflictError("仅 APPLYING 状态可审核 proof")

        proof = await ApplicationRepository.get_proof_by_id(db, proof_id)
        if not proof or proof.application_id != application_id:
            raise NotFoundError("proof 不存在")

        if action == "APPROVED":
            proof.status = ProofStatus.APPROVED.value
        elif action == "REJECTED":
            proof.status = ProofStatus.REJECTED.value
        else:
            raise BadRequestError("action 必须为 APPROVED 或 REJECTED")

        await ApplicationRepository.update_proof(db, proof)
        ApplicationService._ensure_reviewer_id(application, reviewer_id)

        reviewer_name = await ApplicationService.get_user_full_name(db, reviewer_id)
        operation = ApplicationOperation(
            application_id=application.id,
            operator_id=reviewer_id,
            operator_name=reviewer_name,
            operation=f"PROOF_{proof.status}",
            remark=remark,
        )
        await ApplicationRepository.insert_operation(db, operation)

        await ApplicationRepository.commit(db)
        return {"id": proof.id, "applicationId": proof.application_id, "status": proof.status}

    @staticmethod
    async def pass_application(
        db: AsyncSession,
        application_id: int,
        remark: Optional[str] = None,
    ) -> PassResultVO:
        """审核员投票通过"""
        reviewer_id = ApplicationService.get_current_user_id()
        if await ApplicationService._has_voted(db, application_id, reviewer_id):
            raise ConflictError("该审核员已投过票")

        application = await ApplicationRepository.get_with_details(db, application_id, for_update=True)
        if not application:
            raise NotFoundError("申请不存在")
        if application.status != ApplicationStatus.APPLYING.value:
            raise ConflictError(f"申请当前状态 {application.status}，仅 APPLYING 可 PASS")

        pending_count = await ApplicationRepository.count_pending_or_rejected_proofs(db, application_id)
        if pending_count > 0:
            raise ConflictError(f"还有 {pending_count} 份证明未通过，无法 PASS")

        application.approved_count = (application.approved_count or 0) + 1

        if application.approved_count >= application.review_count:
            application.status = ApplicationStatus.PASSED.value
            await ScoreDataService.record(
                db,
                user_id=application.user_id,
                application_id=application.id,
                category_id=application.category_id,
                name=application.template_name,
                score=application.gain_score,
            )

        ApplicationService._ensure_reviewer_id(application, reviewer_id)

        reviewer_name = await ApplicationService.get_user_full_name(db, reviewer_id)
        operation = ApplicationOperation(
            application_id=application.id,
            operator_id=reviewer_id,
            operator_name=reviewer_name,
            operation=ApplicationStatus.PASSED.value,
            remark=remark,
        )
        await ApplicationRepository.insert_operation(db, operation)

        await ApplicationRepository.commit(db)
        await ApplicationRepository.refresh(db, application)
        return PassResultVO.from_orm_to_vo(application)

    @staticmethod
    async def reject_application(
        db: AsyncSession,
        application_id: int,
        remark: str,
    ) -> RejectResultVO:
        """审核员驳回申请"""
        reviewer_id = ApplicationService.get_current_user_id()
        if not remark or not remark.strip():
            raise BadRequestError("remark 必填")
        if await ApplicationService._has_voted(db, application_id, reviewer_id):
            raise ConflictError("该审核员已投过票")

        application = await ApplicationRepository.get_with_details(db, application_id, for_update=True)
        if not application:
            raise NotFoundError("申请不存在")
        if application.status != ApplicationStatus.APPLYING.value:
            raise ConflictError(f"申请当前状态 {application.status}，仅 APPLYING 可 REJECT")

        application.status = ApplicationStatus.REJECTED.value
        application.rejected_count = (application.rejected_count or 0) + 1

        ApplicationService._ensure_reviewer_id(application, reviewer_id)

        reviewer_name = await ApplicationService.get_user_full_name(db, reviewer_id)
        operation = ApplicationOperation(
            application_id=application.id,
            operator_id=reviewer_id,
            operator_name=reviewer_name,
            operation=ApplicationStatus.REJECTED.value,
            remark=remark.strip(),
        )
        await ApplicationRepository.insert_operation(db, operation)

        await ApplicationRepository.commit(db)
        await ApplicationRepository.refresh(db, application)
        return RejectResultVO.from_orm_to_vo(application)

    @staticmethod
    async def revoke(
        db: AsyncSession,
        application_id: int,
        remark: str,
    ) -> dict:
        """撤回已通过的申请"""
        operator_id = ApplicationService.get_current_user_id()
        if not remark or not remark.strip():
            raise BadRequestError("remark 必填")

        application = await ApplicationRepository.get_with_details(db, application_id, for_update=True)
        if not application:
            raise NotFoundError("申请不存在")
        if application.status != ApplicationStatus.PASSED.value:
            raise ConflictError(f"申请当前状态 {application.status}，仅 PASSED 可撤回")

        application.status = ApplicationStatus.REVOKED.value

        operator_name = await ApplicationService.get_user_full_name(db, operator_id)
        operation = ApplicationOperation(
            application_id=application.id,
            operator_id=operator_id,
            operator_name=operator_name,
            operation=ApplicationStatus.REVOKED.value,
            remark=remark.strip(),
        )
        await ApplicationRepository.insert_operation(db, operation)

        await ApplicationRepository.commit(db)
        return {"id": application.id, "status": application.status}

    # ------------------------------------------------------------------
    # 审核员端：列表查询
    # ------------------------------------------------------------------

    @staticmethod
    async def list_pending_for_me(
        db: AsyncSession,
        req: ApplicationQueryRequest,
    ) -> ApplicationListVO:
        """我的待审核列表"""
        reviewer_id = ApplicationService.get_current_user_id()
        applications, total = await ApplicationRepository.list_pending_for_reviewer(db, reviewer_id, req)
        return ApplicationListVO.from_list_to_page(
            items=[ApplicationVO.from_orm_to_vo(a, with_proofs=True) for a in applications],
            total=total,
            page_num=req.pageNum,
            page_size=req.pageSize,
        )

    @staticmethod
    async def list_my_reviewed(
        db: AsyncSession,
        req: ApplicationQueryRequest,
    ) -> ApplicationListVO:
        """我的已审核列表"""
        reviewer_id = ApplicationService.get_current_user_id()
        applications, total = await ApplicationRepository.list_reviewed_by_reviewer(db, reviewer_id, req)
        return ApplicationListVO.from_list_to_page(
            items=[ApplicationVO.from_orm_to_vo(a, with_proofs=True) for a in applications],
            total=total,
            page_num=req.pageNum,
            page_size=req.pageSize,
        )

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    async def _has_voted(
        db: AsyncSession,
        application_id: int,
        reviewer_id: int,
    ) -> bool:
        """检查审核员是否已投票"""
        operations = await ApplicationRepository.list_operations_by_application(db, application_id)
        voted_ops = {ApplicationStatus.PASSED.value, ApplicationStatus.REJECTED.value}
        for op in operations:
            if op.operator_id == reviewer_id and op.operation in voted_ops:
                return True
        return False


__all__ = ["ApplicationService"]
