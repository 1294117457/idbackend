"""加分申请服务（v4.7 统一 Payload + action）

职责：只做业务逻辑和编排，数据库操作委托给 Repository 层。

action 设计：
  - save    ：保存草稿（不校验 proof 完整性）
  - submit  ：新建并提交（校验 proof 完整性）
  - edit    ：编辑草稿并提交（校验 proof 完整性）
  - review  ：审核员投票（pass/reject）

reviewer_ids 设计：
  - 只在 pass/reject 时记录
  - 查询从 application.reviewer_ids 而非 operation 表
  - 原子性：for_update 锁后检查，通过成功才写入
"""
from __future__ import annotations

from decimal import Decimal
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
    def validate_proof_scores(payload: ApplicationPayload) -> None:
        proofs = payload.proofList or []
        if not proofs:
            raise BadRequestError("请至少上传一份证明材料")

        for idx, p in enumerate(proofs, start=1):
            if p.fileId is None:
                raise BadRequestError(f"第 {idx} 份证明材料未上传文件")
            if p.proofScore is None or p.proofScore <= 0:
                raise BadRequestError(f"第 {idx} 份证明材料分值必须大于 0")

        total = sum(p.proofScore for p in proofs)
        if abs(total - payload.applyScore) >= 0.01:
            raise BadRequestError(
                f"证明材料分值总和 {round(total, 2)} 与申请分 {round(payload.applyScore, 2)} 不一致",
            )

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
    ) -> ApplicationVO:
        """保存草稿（新建或更新 DRAFT）

        草稿场景：允许 proof 不完整（用户先保存当前进度，后续再编辑补完）。
        proof 完整性校验仅在 submit / edit_submit（进入审核流前）执行。
        """
        user_id = ApplicationService.get_current_user_id()

        application_id = payload.applicationId

        if application_id is None:
            application = payload.to_application_model(
                user_id=user_id,
                status=ApplicationStatus.DRAFT.value,
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
    ) -> ApplicationVO:
        """新建并提交申请"""
        ApplicationService.validate_proof_scores(payload)
        user_id = ApplicationService.get_current_user_id()
        if payload.applicationId is not None:
            raise BadRequestError("submit 接口 applicationId 必须为空")

        operator_name = await ApplicationService.get_user_full_name(db, user_id)

        application = payload.to_application_model(
            user_id=user_id,
            status=ApplicationStatus.APPLYING.value,
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
        ApplicationService.validate_proof_scores(payload)
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
        # 先设为 None 再设 []，确保 SQLAlchemy 检测到 JSON 字段变更
        application.reviewer_ids = None
        application.reviewer_ids = []

        # 整表替换 proofs（处理 proofId=null 的新 proof、proofId 已有的更新、未在 payload 中的删除）
        await ApplicationService._replace_proofs(db, application.id, payload.proofList)

        # 重新查询当前所有 proofs，把 status 重置为 PENDING
        # （重新提交意味着所有 proof 重新走审核；ORM collection 在 _replace_proofs 删 proof 后可能不准，重新查一次更稳）
        current_proofs = await ApplicationRepository.list_proofs_by_application(db, application.id)
        for proof in current_proofs:
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

    # ------------------------------------------------------------------
    # 审核员端
    # ------------------------------------------------------------------

    @staticmethod
    async def pass_application(
        db: AsyncSession,
        payload: ApplicationPayload,
    ) -> PassResultVO:
        """审核员投票通过（统一 Payload + action）"""
        reviewer_id = ApplicationService.get_current_user_id()

        application = await ApplicationRepository.get_with_details(db, payload.applicationId, for_update=True)
        if not application:
            raise NotFoundError("申请不存在")

        if application.status != ApplicationStatus.APPLYING.value:
            raise ConflictError(f"申请当前状态 {application.status}，仅 APPLYING 可 PASS")

        # 从 application.reviewer_ids 查询是否已投票（原子性：在 for_update 锁后检查）
        if ApplicationService._has_voted(application, reviewer_id):
            raise ConflictError("该审核员已投过票")

        # 批量更新 proofs
        if payload.proofList:
            for p in payload.proofList:
                proof = await ApplicationRepository.get_proof_by_id(db, p.proofId)
                if not proof or proof.application_id != application.id:
                    raise NotFoundError(f"proof {p.proofId} 不存在")
                if p.status not in (ProofStatus.APPROVED.value, ProofStatus.REJECTED.value):
                    raise BadRequestError("proof status 必须为 APPROVED 或 REJECTED")
                proof.status = p.status
                await ApplicationRepository.update_proof(db, proof)

        # 全部通过才算通过（proofs 由前端保证全 APPROVED）
        all_approved = all(p.status == ProofStatus.APPROVED.value for p in application.proofs)
        if not all_approved:
            raise ConflictError("还有证明未通过，无法 PASS")

        # 原子写入：只有通过成功才追加 reviewer_id
        application.reviewer_ids = (application.reviewer_ids or []) + [reviewer_id]
        application.approved_count = (application.approved_count or 0) + 1

        if application.approved_count >= application.review_count:
            application.status = ApplicationStatus.PASSED.value
            application.gain_score = sum(
                p.proof_score for p in application.proofs if p.status == ProofStatus.APPROVED.value
            )
            await ScoreDataService.record(
                db,
                user_id=application.user_id,
                application_id=application.id,
                category_id=application.category_id,
                name=application.template_name,
                score=application.gain_score,
            )

        reviewer_name = await ApplicationService.get_user_full_name(db, reviewer_id)
        operation = ApplicationOperation(
            application_id=application.id,
            operator_id=reviewer_id,
            operator_name=reviewer_name,
            operation=ApplicationStatus.PASSED.value,
            remark=payload.remark,
        )
        await ApplicationRepository.insert_operation(db, operation)

        await ApplicationRepository.commit(db)
        await ApplicationRepository.refresh(db, application)
        return PassResultVO.from_orm_to_vo(application)

    @staticmethod
    async def reject_application(
        db: AsyncSession,
        payload: ApplicationPayload,
    ) -> RejectResultVO:
        """审核员驳回申请（统一 Payload + action）"""
        reviewer_id = ApplicationService.get_current_user_id()

        if not payload.remark or not payload.remark.strip():
            raise BadRequestError("remark 必填")

        application = await ApplicationRepository.get_with_details(db, payload.applicationId, for_update=True)
        if not application:
            raise NotFoundError("申请不存在")

        if application.status != ApplicationStatus.APPLYING.value:
            raise ConflictError(f"申请当前状态 {application.status}，仅 APPLYING 可 REJECT")

        # 从 application.reviewer_ids 查询是否已投票（原子性：在 for_update 锁后检查）
        if ApplicationService._has_voted(application, reviewer_id):
            raise ConflictError("该审核员已投过票")

        # 原子写入：只有驳回成功才追加 reviewer_id
        application.reviewer_ids = (application.reviewer_ids or []) + [reviewer_id]
        application.status = ApplicationStatus.REJECTED.value
        application.rejected_count = (application.rejected_count or 0) + 1

        reviewer_name = await ApplicationService.get_user_full_name(db, reviewer_id)
        operation = ApplicationOperation(
            application_id=application.id,
            operator_id=reviewer_id,
            operator_name=reviewer_name,
            operation=ApplicationStatus.REJECTED.value,
            remark=payload.remark.strip(),
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
        application.gain_score = Decimal("0")

        await ScoreDataService.revoke(db, application.user_id, application.id)

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
        """管理员的审核历史列表（不限制审核人）"""
        applications, total = await ApplicationRepository.list_reviewed_by_reviewer(db, req)
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
    def _has_voted(application: Application, reviewer_id: int) -> bool:
        """检查审核员是否已投票（从 application.reviewer_ids 查询）"""
        return reviewer_id in (application.reviewer_ids or [])


__all__ = ["ApplicationService"]
