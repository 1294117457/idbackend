"""加分申请服务（v5 充血模型）

职责：只做编排，调用模型的领域方法。
业务规则 → models/application.py
格式转换 → schemas/application.py
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
    ApplicationEvent,
    ApplicationSubmitted,
    ApplicationCancelled,
    ApplicationApproved,
    ApplicationRejected,
    ApplicationRevoked,
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
from src.services.template_service import TemplateService
from src.repositories.template_repo import TemplateRepository
from src.app.context import get_user_id as _get_user_id, get_username as _get_username


class ApplicationService:
    """加分申请服务（编排层）"""

    # ── 内部工具 ─────────────────────────────────────────────────────────

    @staticmethod
    def _current_user_id() -> int:
        user_id = _get_user_id()
        if not user_id:
            from src.app.schemas.errors import UnauthorizedError
            raise UnauthorizedError()
        return user_id

    @staticmethod
    async def _user_full_name(db: AsyncSession, user_id: int) -> str:
        user = await db.get(User, user_id)
        return (user.full_name if user else None) or (
            user.username if user else f"user#{user_id}"
        )

    @staticmethod
    def _is_all_proofs_approved(app: Application) -> bool:
        return all(p.status == ProofStatus.APPROVED.value for p in app.proofs)

    @staticmethod
    def _event_to_operation(event: ApplicationEvent) -> ApplicationOperation:
        """将领域事件转换为持久化的操作日志"""
        return ApplicationOperation(
            application_id=event.application_id,
            operator_id=event.operator_id,
            operator_name=event.operator_name,
            operation=event.operation,
            remark=event.remark,
        )

    # ── 学生端 ───────────────────────────────────────────────────────────

    @staticmethod
    async def save_draft(
        db: AsyncSession,
        payload: ApplicationPayload,
    ) -> ApplicationVO:
        """保存草稿（新建或更新 DRAFT）"""
        user_id = ApplicationService._current_user_id()

        if payload.applicationId is None:
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
            application = await ApplicationRepository.get_with_details(
                db, payload.applicationId, for_update=True,
            )
            if application.user_id != user_id:
                raise ForbiddenError("仅本人可编辑草稿")
            if not application.can_be_edited():       # 领域方法：校验 DRAFT 状态
                raise ConflictError(
                    f"申请当前状态 {application.status}，仅 DRAFT 可编辑",
                )

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
        user_id = ApplicationService._current_user_id()
        if payload.applicationId is not None:
            raise BadRequestError("submit 接口 applicationId 必须为空")

        await ApplicationService._check_repeated_submission(
            db, user_id, payload.templateId,
        )
        operator_name = await ApplicationService._user_full_name(db, user_id)

        application = payload.to_application_model(
            user_id=user_id,
            status=ApplicationStatus.APPLYING.value,
        )
        await ApplicationRepository.insert(db, application)

        for proof in payload.build_proofs(application.id):
            await ApplicationRepository.insert_proof(db, proof)

        event = ApplicationSubmitted(
            application_id=application.id,
            operator_id=user_id,
            operator_name=operator_name,
            operation=ApplicationStatus.APPLYING.value,
        )
        await ApplicationRepository.insert_operation(db, ApplicationService._event_to_operation(event))

        await ApplicationRepository.commit(db)
        await ApplicationRepository.refresh(db, application)

        app_with_details = await ApplicationRepository.get_with_details_by_id(db, application.id)
        return ApplicationVO.from_orm_to_vo(app_with_details)

    @staticmethod
    async def edit_submit(
        db: AsyncSession,
        payload: ApplicationPayload,
    ) -> ApplicationVO:
        """编辑后提交（仅 DRAFT / REJECTED / REVOKED 可操作）"""
        ApplicationService.validate_proof_scores(payload)
        user_id = ApplicationService._current_user_id()
        if payload.applicationId is None:
            raise BadRequestError("edit-submit 接口 applicationId 不能为空")

        await ApplicationService._check_repeated_submission(
            db, user_id, payload.templateId, exclude_application_id=payload.applicationId,
        )
        application = await ApplicationRepository.get_with_details(
            db, payload.applicationId, for_update=True,
        )
        if application.user_id != user_id:
            raise ForbiddenError("仅本人可操作")

        operator_name = await ApplicationService._user_full_name(db, user_id)
        event = application.submit(operator_id=user_id, operator_name=operator_name)  # 领域方法：状态校验 + 重置投票 + 返回事件
        payload.apply_to_model(application)

        await ApplicationService._replace_proofs(db, application.id, payload.proofList)

        current_proofs = await ApplicationRepository.list_proofs_by_application(db, application.id)
        for proof in current_proofs:
            proof.status = ProofStatus.PENDING.value

        await ApplicationRepository.insert_operation(db, ApplicationService._event_to_operation(event))

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
        user_id = ApplicationService._current_user_id()
        application = await ApplicationRepository.get_with_details(
            db, application_id, for_update=True,
        )
        if application.user_id != user_id:
            raise ForbiddenError("仅本人可操作")

        operator_name = await ApplicationService._user_full_name(db, user_id)
        event = application.cancel(operator_id=user_id, operator_name=operator_name, remark=remark)  # 领域方法
        await ApplicationRepository.insert_operation(db, ApplicationService._event_to_operation(event))

        await ApplicationRepository.commit(db)
        await ApplicationRepository.refresh(db, application)
        return CancelResultVO.from_orm_to_vo(application)

    @staticmethod
    async def touch(
        db: AsyncSession,
        application_id: int,
    ) -> ApplicationVO:
        """DRAFT 状态下纯刷 updated_at"""
        user_id = ApplicationService._current_user_id()
        application = await ApplicationRepository.get_with_details(db, application_id)

        if application.user_id != user_id:
            raise ForbiddenError("仅本人可操作")
        if not application.can_be_edited():          # 领域方法：校验 DRAFT 状态
            raise ConflictError(f"申请当前状态 {application.status}，仅 DRAFT 可操作")

        await ApplicationRepository.commit(db)

        app_with_details = await ApplicationRepository.get_with_details_by_id(db, application.id)
        return ApplicationVO.from_orm_to_vo(app_with_details)

    # ── 学生端：列表 / 详情 ───────────────────────────────────────────────

    @staticmethod
    async def list_my_applications(
        db: AsyncSession,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> ApplicationListVO:
        """我的申请列表"""
        user_id = ApplicationService._current_user_id()
        applications, total = await ApplicationRepository.list_by_user(
            db, user_id, status, page, size,
        )
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
            raise NotFoundError("申请不存在")

        operations = await ApplicationRepository.list_operations_by_application(db, application_id)
        return ApplicationDetailVO.from_orm_to_vo(application, operations)

    # ── 审核员端 ───────────────────────────────────────────────────────────

    @staticmethod
    async def pass_application(
        db: AsyncSession,
        payload: ApplicationPayload,
    ) -> PassResultVO:
        """审核员投票通过"""
        reviewer_id = ApplicationService._current_user_id()

        application = await ApplicationRepository.get_with_details(
            db, payload.applicationId, for_update=True,
        )
        if not application:
            raise NotFoundError("申请不存在")

        # 批量更新 proofs
        if payload.proofList:
            for p in payload.proofList:
                proof = await ApplicationRepository.get_proof_by_id(db, p.proofId)
                if not proof or proof.application_id != application.id:
                    raise NotFoundError(f"proof {p.proofId} 不存在")
                if p.status not in (
                    ProofStatus.APPROVED.value,
                    ProofStatus.REJECTED.value,
                ):
                    raise BadRequestError("proof status 必须为 APPROVED 或 REJECTED")
                if p.status == ProofStatus.APPROVED.value:
                    proof.approve()                  # 领域方法
                else:
                    proof.reject()                   # 领域方法
                await ApplicationRepository.update_proof(db, proof)

        # 全部 proof APPROVED 才允许 PASS
        if not ApplicationService._is_all_proofs_approved(application):
            raise ConflictError("还有证明未通过，无法 PASS")

        reviewer_name = await ApplicationService._user_full_name(db, reviewer_id)

        # 领域方法：投票 + 终态判断 + 得分计算
        event = application.approve(
            reviewer_id=reviewer_id,
            operator_id=reviewer_id,
            operator_name=reviewer_name,
        )

        # PASSED → 记分
        if event.is_final:
            await ScoreDataService.record(
                db,
                user_id=application.user_id,
                application_id=application.id,
                category_id=application.category_id,
                name=application.template_name,
                score=application.gain_score,
            )

        # remark 附加到事件（通过 _event_to_operation 持久化）
        event.remark = payload.remark
        await ApplicationRepository.insert_operation(db, ApplicationService._event_to_operation(event))

        await ApplicationRepository.commit(db)
        await ApplicationRepository.refresh(db, application)
        return PassResultVO.from_orm_to_vo(application)

    @staticmethod
    async def reject_application(
        db: AsyncSession,
        payload: ApplicationPayload,
    ) -> RejectResultVO:
        """审核员驳回申请"""
        reviewer_id = ApplicationService._current_user_id()

        if not payload.remark or not payload.remark.strip():
            raise BadRequestError("remark 必填")

        application = await ApplicationRepository.get_with_details(
            db, payload.applicationId, for_update=True,
        )
        if not application:
            raise NotFoundError("申请不存在")

        reviewer_name = await ApplicationService._user_full_name(db, reviewer_id)
        event = application.reject(
            reviewer_id=reviewer_id,
            operator_id=reviewer_id,
            operator_name=reviewer_name,
            remark=payload.remark.strip(),
        )  # 领域方法
        await ApplicationRepository.insert_operation(db, ApplicationService._event_to_operation(event))

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
        operator_id = ApplicationService._current_user_id()
        if not remark or not remark.strip():
            raise BadRequestError("remark 必填")

        application = await ApplicationRepository.get_with_details(
            db, application_id, for_update=True,
        )
        if not application:
            raise NotFoundError("申请不存在")

        operator_name = await ApplicationService._user_full_name(db, operator_id)
        event = application.revoke(
            operator_id=operator_id,
            operator_name=operator_name,
            remark=remark.strip(),
        )  # 领域方法：状态校验 + 写 REVOKED + 清 gain_score + 返回事件
        await ApplicationRepository.insert_operation(db, ApplicationService._event_to_operation(event))

        await ScoreDataService.revoke(db, application.user_id, application.id)

        await ApplicationRepository.commit(db)
        return {"id": application.id, "status": application.status}

    # ── 审核员端：列表查询 ───────────────────────────────────────────────

    @staticmethod
    async def list_pending_for_me(
        db: AsyncSession,
        req: ApplicationQueryRequest,
    ) -> ApplicationListVO:
        """管理员的待审核列表"""
        applications, total = await ApplicationRepository.list_pending_for_reviewer(db, req)
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
        """管理员的审核历史列表"""
        applications, total = await ApplicationRepository.list_reviewed_by_reviewer(db, req)
        return ApplicationListVO.from_list_to_page(
            items=[ApplicationVO.from_orm_to_vo(a, with_proofs=True) for a in applications],
            total=total,
            page_num=req.pageNum,
            page_size=req.pageSize,
        )

    # ── 内部辅助 ─────────────────────────────────────────────────────────

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
    async def _check_repeated_submission(
        db: AsyncSession,
        user_id: int,
        template_id: int,
        exclude_application_id: Optional[int] = None,
    ) -> None:
        """重复提交校验

        v9：只读 is_repeated 字段，跳过 description 的占位替换（与图片展示无关）。
        """
        template = await TemplateRepository.get_by_id(db, template_id)
        if template is None:
            # 与 TemplateService.get_by_id 的语义保持一致：缺模板抛 NotFoundError
            from src.app.schemas.errors import NotFoundError
            raise NotFoundError(f"模板(id={template_id})不存在")
        if not template.is_repeated:
            existing = await ApplicationRepository.check_user_template_duplicate(
                db, user_id, template_id, exclude_application_id,
            )
            if existing:
                raise ConflictError("该模板不允许重复提交，您已有进行中的申请")

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


__all__ = ["ApplicationService"]
