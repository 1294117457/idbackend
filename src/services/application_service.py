"""加分申请服务（v4.4）

═══════════════════════════════════════════════════════════════════════
v4.4 关键设计变更（相对于 v4.3）
═══════════════════════════════════════════════════════════════════════
1. submit 统一为单一接口：DRAFT/REJECTED/REVOKED → APPLYING
   - 旧的 submit（仅 DRAFT）和 resubmit 合并为 submit
2. update_draft 废弃：证明材料改为单 proof CRUD
   - 新增：create_proof / delete_proof / update_proof_score / replace_proof_file
3. proof 可编辑条件（学生端）：
   - application.status ∈ {DRAFT, REJECTED, REVOKED}
   - proof.status ∈ {PENDING, REJECTED, APPROVED}（APPROVED 也允许学生重传为 PENDING）
4. touch 接口：DRAFT 状态下纯刷 updated_at（前端"保存草稿"按钮用）
5. pass_application 前置条件：所有 proof.status=='APPROVED'

═══════════════════════════════════════════════════════════════════════
状态机（application）
═══════════════════════════════════════════════════════════════════════
  DRAFT       - 草稿（学生可编辑所有 proof）
  APPLYING    - 审核中（学生锁定）
  PASSED      - 已通过（终态）
  REJECTED    - 已驳回（可重提）
  CANCELLED   - 已取消（终态，学生主动取消）
  REVOKED     - 已撤回（终态，老师撤回）

═══════════════════════════════════════════════════════════════════════
proof 状态机
═══════════════════════════════════════════════════════════════════════
  PENDING     - 待审核
  APPROVED    - 已通过（审核员投票）
  REJECTED    - 已驳回（审核员投票）

  学生可在 application ∈ {DRAFT, REJECTED, REVOKED} 时修改 proof：
    - 替换文件 → 重置 PENDING
    - 删除 proof → 物理删除
    - 修改 proof_score → 不改 status
═══════════════════════════════════════════════════════════════════════
事务边界（关键）
═══════════════════════════════════════════════════════════════════════
所有方法都在单一 async 函数内 commit——service 调用方不需自己开事务。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional, List, Dict, Any, Union

from sqlalchemy import select, and_, func, or_, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
from src.app.schemas import ApplicationPayload, ProofPayload


# ════════════════════════════════════════════════════════════════════════
# 错误码
# ════════════════════════════════════════════════════════════════════════
class ApplicationErrorCode:
    APPLICATION_NOT_FOUND = "APPLICATION_NOT_FOUND"
    NOT_OWNER = "NOT_OWNER"
    INVALID_STATUS = "INVALID_STATUS"
    NO_PROOFS = "NO_PROOFS"
    PROOF_SUM_MISMATCH = "PROOF_SUM_MISMATCH"
    HAS_PENDING_OR_REJECTED_PROOF = "HAS_PENDING_OR_REJECTED_PROOF"
    ALREADY_VOTED = "ALREADY_VOTED"
    PROOF_NOT_FOUND = "PROOF_NOT_FOUND"
    REVIEWER_ALREADY_REVIEWED_THIS_PROOF = "REVIEWER_ALREADY_REVIEWED_THIS_PROOF"


# ════════════════════════════════════════════════════════════════════════
# ApplicationService（v4.2）
# ════════════════════════════════════════════════════════════════════════
class ApplicationService:
    """加分申请服务（v4.2）"""

    # ------------------------------------------------------------------
    # 4.1 save_draft（v4.5：支持 applicationId=None=新建 / 非空=更新 DRAFT）
    # ------------------------------------------------------------------
    @staticmethod
    async def save_draft(
        db: AsyncSession,
        user_id: int,
        payload: ApplicationPayload,
        review_count: int = 1,
    ) -> Application:
        """保存草稿（v4.5：applicationId 决定新建/更新）

        输入:
          - user_id: 学生 id
          - payload: ApplicationPayload（含 proofs 整表替换）
          - review_count: 从模板快照（路由层传入，不接受客户端直接传值）

        分支:
          - payload.applicationId is None
              → 新建 application（status='DRAFT'）
              → 同 template 下若已存在 APPLYING/PASSED 申请则抛 ConflictError
          - payload.applicationId 非空
              → 更新现有 application（仅 DRAFT 状态可更新）
              → 整表替换 proofs

        行为（更新场景）:
          1. 校验本人 + status == DRAFT
          2. 更新 apply_score / template_name / category_id / remark
          3. _replace_proofs：diff 更新（按 proofId 整表替换）
        """
        # 1. 校验 user
        user = await db.get(User, user_id)
        if not user:
            raise NotFoundError(f"用户(id={user_id})不存在")

        application_id = payload.applicationId
        if application_id is None:
            # ── 新建分支 ───────────────────────────────────────────────
            # v4.5：不再校验"同模板是否有 APPLYING/PASSED 活申请"
            # 业务场景：一个模板可反复提交（如多次获奖）

            application = Application(
                user_id=user_id,
                template_id=payload.templateId,
                template_name=payload.templateName,
                category_id=payload.categoryId,
                apply_score=Decimal(str(payload.applyScore)),
                gain_score=Decimal("0"),
                status=ApplicationStatus.DRAFT.value,
                review_count=review_count,
                approved_count=0,
                rejected_count=0,
            )
            db.add(application)
            await db.flush()  # 拿到 application.id

            # 新建场景下所有 proof 都是新建
            for pp in payload.proofList:
                proof = ApplicationProof(
                    application_id=application.id,
                    file_id=pp.fileId,
                    proof_score=Decimal(str(pp.proofScore)),
                    status=ProofStatus.PENDING.value,
                )
                db.add(proof)

            await db.commit()
            await db.refresh(application)
        else:
            # ── 更新分支 ───────────────────────────────────────────────
            application = await ApplicationService._get_for_update(db, application_id)

            if application.user_id != user_id:
                raise ForbiddenError("仅本人可编辑草稿")
            if application.status != ApplicationStatus.DRAFT.value:
                raise ConflictError(
                    f"申请当前状态 {application.status}，仅 DRAFT 可编辑"
                )

            # 更新 application 字段
            application.template_id = payload.templateId
            application.template_name = payload.templateName
            application.category_id = payload.categoryId
            application.apply_score = Decimal(str(payload.applyScore))
            application.remark = payload.remark

            # 整表替换 proofs
            await ApplicationService._replace_proofs(
                db,
                application_id=application.id,
                proof_list=payload.proofList,
            )

            await db.commit()
            await db.refresh(application)

        result = await db.execute(
            select(Application)
            .options(selectinload(Application.proofs), selectinload(Application.user))
            .where(Application.id == application.id)
        )
        return result.scalar_one()

    # ------------------------------------------------------------------
    # 整表替换 proofs（v4.5 新增；saveDraft / editSubmit 共用）
    # ------------------------------------------------------------------
    @staticmethod
    async def _replace_proofs(
        db: AsyncSession,
        application_id: int,
        proof_list: List[ProofPayload],
    ) -> None:
        """根据 payload.proofList 整表替换该 application 下的 proofs。

        语义：
          - payload 里 proofId 非空 + DB 里存在该 proof：
                → 更新；fileId 变化则 status 重置 PENDING
                → proofScore 总是更新为新值
          - payload 里 proofId 非空 + DB 里不存在：
                → 抛 BadRequestError（前端 bug 或误传）
          - payload 里 proofId 为空：
                → 新建（status=PENDING）
          - DB 里 proofId 存在 + payload 里没有：
                → 物理删除

        校验：
          - 总 proofScore 之和 == application.apply_score（仅在 _replace_proofs
            内做"编辑后状态"级别的硬校验；submit/editSubmit 会再做一次最终校验）
        """
        result = await db.execute(
            select(ApplicationProof).where(
                ApplicationProof.application_id == application_id
            )
        )
        old_proofs: Dict[int, ApplicationProof] = {p.id: p for p in result.scalars().all()}

        payload_ids: set[int] = set()
        for pp in proof_list:
            if pp.proofId is not None:
                payload_ids.add(pp.proofId)

        # 1) 删除：旧里有 + payload 没有
        for old_id in (set(old_proofs) - payload_ids):
            await db.delete(old_proofs[old_id])

        # 2) 更新或新建
        for pp in proof_list:
            new_score = Decimal(str(pp.proofScore))
            if pp.proofId is not None:
                old = old_proofs.get(pp.proofId)
                if old is None:
                    raise BadRequestError(
                        f"proof(id={pp.proofId})不存在或不属于该申请"
                    )
                old.proof_score = new_score
                if pp.fileId != old.file_id:
                    # 文件被替换 → 重置为待审核
                    old.file_id = pp.fileId
                    old.status = ProofStatus.PENDING.value
            else:
                proof = ApplicationProof(
                    application_id=application_id,
                    file_id=pp.fileId,
                    proof_score=new_score,
                    status=ProofStatus.PENDING.value,
                )
                db.add(proof)

    # ------------------------------------------------------------------
    # 4.2 cancel（学生取消草稿/申请）
    # ------------------------------------------------------------------
    @staticmethod
    async def cancel(
        db: AsyncSession,
        application_id: int,
        user_id: int,
        operator_name: str,
        remark: Optional[str] = None,
    ) -> Application:
        """取消草稿/申请 DRAFT/APPLYING → CANCELLED（终态）"""
        application = await ApplicationService._get_for_update(db, application_id)

        if application.user_id != user_id:
            raise ForbiddenError("仅本人可操作")
        if application.status not in (ApplicationStatus.DRAFT.value, ApplicationStatus.APPLYING.value):
            raise ConflictError(
                f"申请当前状态 {application.status}，仅 DRAFT 或 APPLYING 可取消"
            )

        application.status = ApplicationStatus.CANCELLED.value

        op = ApplicationOperation(
            application_id=application.id,
            operator_id=user_id,
            operator_name=operator_name,
            operation=ApplicationStatus.CANCELLED.value,
            remark=remark,
        )
        db.add(op)
        await db.commit()
        await db.refresh(application)
        return application

    # ------------------------------------------------------------------
    # 4.3 submit（v4.5：新建模式，仅接收 ApplicationPayload，applicationId 必须 None）
    # ------------------------------------------------------------------
    @staticmethod
    async def submit(
        db: AsyncSession,
        user_id: int,
        payload: ApplicationPayload,
        operator_name: str,
        review_count: int = 1,
    ) -> Application:
        """新建并提交（v4.5）

        payload.applicationId 必须为 None（提交新建的申请）。
        流程：
          1. 校验 user
          2. INSERT application（status='APPLYING'）
          3. 批量 INSERT proofs（status='PENDING'）
          4. 校验 proof 集合：len≥1 + sum==apply_score
          5. INSERT application_operation(APPLYING)
        """
        if payload.applicationId is not None:
            raise BadRequestError("submit 仅支持新建，请使用 edit-submit 编辑后提交")

        # 校验 user
        user = await db.get(User, user_id)
        if not user:
            raise NotFoundError(f"用户(id={user_id})不存在")

        # v4.5：不再校验同模板重复提交

        # proof 集合校验（前置，能 fail-fast）
        await ApplicationService._validate_payload_proof_sum(payload)

        # INSERT application
        application = Application(
            user_id=user_id,
            template_id=payload.templateId,
            template_name=payload.templateName,
            category_id=payload.categoryId,
            apply_score=Decimal(str(payload.applyScore)),
            gain_score=Decimal("0"),
            status=ApplicationStatus.APPLYING.value,
            review_count=review_count,
            approved_count=0,
            rejected_count=0,
            reviewer_ids=[],
        )
        db.add(application)
        await db.flush()  # 拿 id

        # INSERT proofs
        for pp in payload.proofList:
            proof = ApplicationProof(
                application_id=application.id,
                file_id=pp.fileId,
                proof_score=Decimal(str(pp.proofScore)),
                status=ProofStatus.PENDING.value,
            )
            db.add(proof)

        # INSERT application_operation(APPLYING)
        op = ApplicationOperation(
            application_id=application.id,
            operator_id=user_id,
            operator_name=operator_name,
            operation=ApplicationStatus.APPLYING.value,
            remark=payload.remark,
        )
        db.add(op)

        await db.commit()
        await db.refresh(application)
        result = await db.execute(
            select(Application)
            .options(selectinload(Application.proofs), selectinload(Application.user))
            .where(Application.id == application.id)
        )
        return result.scalar_one()

    # ------------------------------------------------------------------
    # 4.3.1 edit_submit（v4.5 新增：编辑已有 DRAFT/REJECTED/REVOKED 后提交）
    # ------------------------------------------------------------------
    @staticmethod
    async def edit_submit(
        db: AsyncSession,
        user_id: int,
        payload: ApplicationPayload,
        operator_name: str,
    ) -> Application:
        """编辑后提交（DRAFT/REJECTED/REVOKED → APPLYING，v4.5 新增）

        payload.applicationId 必须非空。
        流程：
          1. 锁定 application，校验本人 + status ∈ {DRAFT, REJECTED, REVOKED}
          2. 更新 application 字段（templateName/category/applyScore/remark）
          3. _replace_proofs：整表替换 proofs（proofId 决定新建/更新/删除）
          4. 校验 proof 集合：len≥1 + sum==apply_score
          5. status='APPLYING' + 重置 reviewer_ids / approved_count / rejected_count
          6. INSERT application_operation(APPLYING)
        """
        if payload.applicationId is None:
            raise BadRequestError("edit-submit 必须传 applicationId，请使用 submit 新建")

        application = await ApplicationService._get_for_update(db, payload.applicationId)

        if application.user_id != user_id:
            raise ForbiddenError("仅本人可提交")
        if application.status not in (
            ApplicationStatus.DRAFT.value,
            ApplicationStatus.REJECTED.value,
            ApplicationStatus.REVOKED.value,
        ):
            raise ConflictError(
                f"申请当前状态 {application.status}，仅 DRAFT/REJECTED/REVOKED 可编辑后提交"
            )

        # 更新 application 字段
        application.template_id = payload.templateId
        application.template_name = payload.templateName
        application.category_id = payload.categoryId
        application.apply_score = Decimal(str(payload.applyScore))
        application.remark = payload.remark

        # 整表替换 proofs
        await ApplicationService._replace_proofs(
            db,
            application_id=application.id,
            proof_list=payload.proofList,
        )

        # proof 集合校验（前置 fail-fast）
        await ApplicationService._validate_payload_proof_sum(payload)

        # 状态机推进 + 计数器重置
        application.status = ApplicationStatus.APPLYING.value
        application.reviewer_ids = []
        application.approved_count = 0
        application.rejected_count = 0

        op = ApplicationOperation(
            application_id=application.id,
            operator_id=user_id,
            operator_name=operator_name,
            operation=ApplicationStatus.APPLYING.value,
            remark=payload.remark,
        )
        db.add(op)

        await db.commit()
        await db.refresh(application)
        result = await db.execute(
            select(Application)
            .options(selectinload(Application.proofs), selectinload(Application.user))
            .where(Application.id == application.id)
        )
        return result.scalar_one()

    @staticmethod
    async def _validate_payload_proof_sum(payload: ApplicationPayload) -> None:
        """校验 payload.proofList：≥ 1 条 + sum == apply_score（v4.5 新增）"""
        if len(payload.proofList) < 1:
            raise BadRequestError("submit 必须至少 1 条证明")
        total = sum((Decimal(str(p.proofScore)) for p in payload.proofList), Decimal("0"))
        if total != Decimal(str(payload.applyScore)):
            raise BadRequestError(
                f"proof_score 之和 {total} != apply_score {payload.applyScore}"
            )

    @staticmethod
    def _ensure_reviewer_id(app: Application, reviewer_id: int) -> None:
        """将 reviewer_id 追加到 reviewer_ids 列表（防重）"""
        if app.reviewer_ids is None:
            app.reviewer_ids = []
        if reviewer_id not in app.reviewer_ids:
            app.reviewer_ids = app.reviewer_ids + [reviewer_id]

    # ------------------------------------------------------------------
    # 4.3 review_proof（审核员审 proof）—— v4.3 新增 reviewer_ids 写入
    # ------------------------------------------------------------------
    @staticmethod
    async def review_proof(
        db: AsyncSession,
        proof_id: int,
        reviewer_id: int,
        action: str,
        remark: Optional[str] = None,
    ) -> ApplicationProof:
        """审核员对单条 proof 做出 APPROVED / REJECTED 决定（v4.3）

        关键决策（v4.3 变更）:
          - proof APPROVED: 同事务原子 gain_score += proof_score
          - proof APPROVED→REJECTED: 同事务原子 gain_score -= proof_score
          - 不写 application_operation（proof 是辅助表）
          - 不强制 remark

        前置条件:
          1. proof.application_id 对应的 application.status == 'APPLYING'
        """
        if action not in (ProofStatus.APPROVED.value, ProofStatus.REJECTED.value):
            raise BadRequestError(f"action 必须是 APPROVED 或 REJECTED，当前: {action}")

        stmt = (
            select(ApplicationProof)
            .options(selectinload(ApplicationProof.application))
            .where(ApplicationProof.id == proof_id)
        )
        result = await db.execute(stmt)
        proof = result.scalar_one_or_none()
        if not proof:
            raise NotFoundError(f"proof(id={proof_id})不存在")

        application = proof.application
        if application.status != ApplicationStatus.APPLYING.value:
            raise ConflictError(
                f"application 当前状态 {application.status}，仅 APPLYING 可 review_proof"
            )

        old_status = proof.status
        proof.status = action

        # 原子更新 gain_score（SQL 表达式，同事务）
        if old_status != ProofStatus.APPROVED.value and action == ProofStatus.APPROVED.value:
            # PENDING/REJECTED → APPROVED：累加
            await db.execute(
                update(Application)
                .where(Application.id == application.id)
                .values(gain_score=Application.gain_score + proof.proof_score)
            )
        elif old_status == ProofStatus.APPROVED.value and action == ProofStatus.REJECTED.value:
            # APPROVED → REJECTED：扣减
            await db.execute(
                update(Application)
                .where(Application.id == application.id)
                .values(gain_score=Application.gain_score - proof.proof_score)
            )
        # PENDING→REJECTED 或 APPROVED→APPROVED：gain_score 不变

        # v4.3: 追加 reviewer_id（审过 proof 即算审过此 application）
        ApplicationService._ensure_reviewer_id(application, reviewer_id)

        await db.commit()
        await db.refresh(proof)
        return proof

    # ------------------------------------------------------------------
    # 4.6 pass_application（审核员投 PASS）
    # ------------------------------------------------------------------
    @staticmethod
    async def pass_application(
        db: AsyncSession,
        application_id: int,
        reviewer_id: int,
        reviewer_name: str,
        remark: Optional[str] = None,
    ) -> Application:
        """审核员投票通过 application

        前置条件:
          1. application.status == 'APPLYING'
          2. 该 application 下所有 proof.status == 'APPROVED'
             （COUNT(proof.status IN ('PENDING','REJECTED')) == 0）
          3. (application_id, reviewer_id) 在 application_operation 上 PASS/REJECT 不存在

        同一事务:
          a. SELECT application FOR UPDATE
          b. UPDATE approved_count = approved_count + 1（CAS 单 SQL）
          c. 若 approved_count == review_count：
             - UPDATE status='PASSED', gain_score=apply_score
             - ScoreDataService.record(... apply_score ...)
          d. INSERT application_operation(PASS)

        业务场景:
          - review_count=1：单人审核，A 审完所有 proof + 投 PASS → 立即 PASSED
          - review_count≥2：多人会签，必须 N 个不同审核员都投 PASS 才 PASSED
        """
        # 0. 校验是否已投过票（提前 short-circuit 避免锁）
        has_voted = await ApplicationService.has_voted(
            db, application_id, reviewer_id,
        )
        if has_voted:
            raise ConflictError("该审核员已投过票")

        # 1. SELECT application FOR UPDATE
        application = await ApplicationService._get_for_update(db, application_id)

        if application.status != ApplicationStatus.APPLYING.value:
            raise ConflictError(
                f"申请当前状态 {application.status}，仅 APPLYING 可 PASS"
            )

        # 2. 校验所有 proof.status == 'APPROVED'
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
        bad_proofs = result.scalar() or 0
        if bad_proofs > 0:
            raise ConflictError(
                f"还有 {bad_proofs} 份证明未通过，无法 PASS application"
            )

        # 3. 原子 CAS：approved_count += 1（防止并发同审核员重复投票）
        bind = db.bind
        if bind and getattr(bind.dialect, "name", None) == "postgresql":
            result = await db.execute(
                select(Application)
                .where(
                    and_(
                        Application.id == application_id,
                        Application.status == ApplicationStatus.APPLYING.value,
                    )
                )
                .with_for_update()
            )
        else:
            result = await db.execute(
                select(Application)
                .where(
                    and_(
                        Application.id == application_id,
                        Application.status == ApplicationStatus.APPLYING.value,
                    )
                )
            )
        application = result.scalar_one()

        # 再校验投票去重（再次 short-circuit 防 TOCTOU）
        if await ApplicationService.has_voted(db, application_id, reviewer_id):
            raise ConflictError("该审核员已投过票")

        application.approved_count = (application.approved_count or 0) + 1

        # 4. 若达成 review_count → PASSED
        if application.approved_count >= application.review_count:
            application.status = ApplicationStatus.PASSED.value
            # v4.3：gain_score 已由 review_proof 实时维护，不在此赋值

            # 5. 同事务写 score_data（函数级延迟导入，避免循环依赖）
            from src.services.score_data_service import ScoreDataService
            await ScoreDataService.record(
                db,
                user_id=application.user_id,
                application_id=application.id,
                category_id=application.category_id,
                name=application.template_name,
                score=application.gain_score,
            )

        # 6. 写 operation
        op = ApplicationOperation(
            application_id=application.id,
            operator_id=reviewer_id,
            operator_name=reviewer_name,
            operation=ApplicationStatus.PASSED.value,
            remark=remark,
        )
        db.add(op)

        # v4.3: 追加 reviewer_id
        ApplicationService._ensure_reviewer_id(application, reviewer_id)

        await db.commit()
        await db.refresh(application)
        return application

    # ------------------------------------------------------------------
    # 4.7 reject_application（veto）
    # ------------------------------------------------------------------
    @staticmethod
    async def reject_application(
        db: AsyncSession,
        application_id: int,
        reviewer_id: int,
        reviewer_name: str,
        remark: str,
    ) -> Application:
        """审核员驳回 application（veto）

        前置条件:
          1. application.status == 'APPLYING'
          2. remark.strip() 非空（必填）
          3. (reviewer_id, application_id) 未投过票

        同一事务:
          - UPDATE application SET status='REJECTED', rejected_count+=1
          - INSERT application_operation(REJECT)
        """
        if not remark or not remark.strip():
            raise BadRequestError("remark 必填")

        if await ApplicationService.has_voted(db, application_id, reviewer_id):
            raise ConflictError("该审核员已投过票")

        application = await ApplicationService._get_for_update(db, application_id)

        if application.status != ApplicationStatus.APPLYING.value:
            raise ConflictError(
                f"申请当前状态 {application.status}，仅 APPLYING 可 REJECT"
            )

        application.status = ApplicationStatus.REJECTED.value
        application.rejected_count = (application.rejected_count or 0) + 1

        op = ApplicationOperation(
            application_id=application.id,
            operator_id=reviewer_id,
            operator_name=reviewer_name,
            operation=ApplicationStatus.REJECTED.value,
            remark=remark.strip(),
        )
        db.add(op)

        # v4.3: 追加 reviewer_id
        ApplicationService._ensure_reviewer_id(application, reviewer_id)

        await db.commit()
        await db.refresh(application)
        return application


    # ------------------------------------------------------------------
    # 4.7 revoke（审核员撤回已通过的申请）
    # ------------------------------------------------------------------
    @staticmethod
    async def revoke(
        db: AsyncSession,
        application_id: int,
        operator_id: int,
        operator_name: str,
        remark: str,
    ) -> Application:
        """审核员撤回申请

        前置条件:
          1. (PASSED 状态) → 撤回为 REVOKED
          2. (APPLYING 状态 且 reviewer_ids 包含当前审核员) → 提前结束为 REJECTED
          3. remark.strip() 非空

        同一事务:
          - UPDATE application SET status=?
          - INSERT application_operation(REVOKE/REJECT)
        """
        if not remark or not remark.strip():
            raise BadRequestError("撤回原因 remark 必填")

        application = await ApplicationService._get_for_update(db, application_id)

        if application.status == ApplicationStatus.PASSED.value:
            application.status = ApplicationStatus.REVOKED.value
            op = ApplicationOperation(
                application_id=application.id,
                operator_id=operator_id,
                operator_name=operator_name,
                operation=ApplicationStatus.REVOKED.value,
                remark=remark.strip(),
            )
            db.add(op)

        elif application.status == ApplicationStatus.APPLYING.value:
            reviewer_ids = application.reviewer_ids or []
            if operator_id not in reviewer_ids:
                raise ForbiddenError("非审核参与者，无权撤回此申请")
            application.status = ApplicationStatus.REJECTED.value
            application.rejected_count = (application.rejected_count or 0) + 1
            op = ApplicationOperation(
                application_id=application.id,
                operator_id=operator_id,
                operator_name=operator_name,
                operation=ApplicationStatus.REJECTED.value,
                remark=remark.strip(),
            )
            db.add(op)
        else:
            raise BadRequestError(
                f"申请当前状态 {application.status}，仅 PASSED / APPLYING 可撤回"
            )

        await db.commit()
        await db.refresh(application)
        return application

    # ------------------------------------------------------------------
    # 4.8 touch（DRAFT 状态下纯刷 updated_at，供前端"保存草稿"按钮）
    # ------------------------------------------------------------------
    @staticmethod
    async def touch(
        db: AsyncSession,
        application_id: int,
        user_id: int,
    ) -> Application:
        """纯刷 updated_at。仅 DRAFT 状态可触发。

        不修改任何 proof、不修改 application 字段（updated_at 除外）。
        用于前端"保存草稿"按钮的语义占位。
        """
        application = await ApplicationService._get_for_update(db, application_id)

        if application.user_id != user_id:
            raise ForbiddenError("仅本人可操作")
        if application.status != ApplicationStatus.DRAFT.value:
            raise ConflictError(
                f"申请当前状态 {application.status}，仅 DRAFT 可触发保存草稿"
            )

        # 显式标记字段为已修改以触发 onupdate=func.now()
        application.updated_at = func.now()

        await db.commit()
        await db.refresh(application)

        result = await db.execute(
            select(Application)
            .options(selectinload(Application.proofs))
            .where(Application.id == application.id)
        )
        return result.scalar_one()

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    @staticmethod
    async def _get_for_update(
        db: AsyncSession,
        application_id: int,
    ) -> Application:
        """SELECT ... FOR UPDATE（PG）/ 普通 SELECT（sqlite 测试环境）"""
        from sqlalchemy.dialects.postgresql import dialect as pg_dialect
        bind = db.bind
        if bind and getattr(bind.dialect, "name", None) == "postgresql":
            stmt = (
                select(Application)
                .where(Application.id == application_id)
                .options(selectinload(Application.user))
                .with_for_update()
            )
        else:
            stmt = (
                select(Application)
                .where(Application.id == application_id)
                .options(selectinload(Application.user))
            )
        result = await db.execute(stmt)
        application = result.scalar_one_or_none()
        if not application:
            raise NotFoundError(f"申请(id={application_id})不存在")
        return application

    @staticmethod
    async def has_voted(
        db: AsyncSession,
        application_id: int,
        reviewer_id: int,
    ) -> bool:
        """判断 (application_id, reviewer_id) 是否已投过票（PASS 或 REJECT）"""
        result = await db.execute(
            select(func.count())
            .select_from(ApplicationOperation)
            .where(
                and_(
                    ApplicationOperation.application_id == application_id,
                    ApplicationOperation.operator_id == reviewer_id,
                    ApplicationOperation.operation.in_([
                        ApplicationStatus.PASSED.value,
                        ApplicationStatus.REJECTED.value,
                    ]),
                )
            )
        )
        return (result.scalar() or 0) > 0

    # ------------------------------------------------------------------
    # 查询接口（按需）
    # ------------------------------------------------------------------
    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        application_id: int,
    ) -> Optional[Application]:
        result = await db.execute(
            select(Application)
            .options(
                selectinload(Application.proofs),
                selectinload(Application.operations),
                selectinload(Application.user),
            )
            .where(Application.id == application_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_user_applications(
        db: AsyncSession,
        user_id: int,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[List[Application], int]:
        """学生的申请列表"""
        from src.models import User
        query = select(Application).where(Application.user_id == user_id)
        if status:
            query = query.where(Application.status == status)

        count_q = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_q)).scalar() or 0

        query = (
            query.options(
                selectinload(Application.proofs),
                selectinload(Application.user),
            )
            .order_by(Application.created_at.asc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await db.execute(query)
        return list(result.scalars().all()), total

    @staticmethod
    async def list_pending_applications(
        db: AsyncSession,
        page: int = 1,
        size: int = 20,
    ) -> tuple[List[Application], int]:
        """待审核列表（status=APPLYING）"""
        query = select(Application).where(
            Application.status == ApplicationStatus.APPLYING.value
        )

        count_q = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_q)).scalar() or 0

        query = (
            query.options(
                selectinload(Application.proofs),
                selectinload(Application.user),
            )
            .order_by(Application.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await db.execute(query)
        return list(result.scalars().all()), total

    @staticmethod
    async def list_audit_history(
        db: AsyncSession,
        page: int = 1,
        size: int = 20,
    ) -> tuple[List[Application], int]:
        """审核历史（PASSED / REJECTED / CANCELLED / REVOKED）"""
        query = select(Application).where(
            Application.status.in_([
                ApplicationStatus.PASSED.value,
                ApplicationStatus.REJECTED.value,
                ApplicationStatus.CANCELLED.value,
                ApplicationStatus.REVOKED.value,
            ])
        )

        count_q = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_q)).scalar() or 0

        query = (
            query.options(
                selectinload(Application.proofs),
                selectinload(Application.user),
            )
            .order_by(Application.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await db.execute(query)
        return list(result.scalars().all()), total

    @staticmethod
    async def list_my_audit_history(
        db: AsyncSession,
        reviewer_id: int,
        page: int = 1,
        size: int = 20,
    ) -> tuple[List[Application], int]:
        """当前审核员操作过的申请（去重，按最新操作时间排序）

        只包含 PASSED/REJECTED 操作（老师投票）
        """
        from src.models import ApplicationOperation

        # 子查询：审核员操作过的 application_id
        op_subq = (
            select(ApplicationOperation.application_id)
            .where(
                and_(
                    ApplicationOperation.operator_id == reviewer_id,
                    ApplicationOperation.operation.in_([
                        ApplicationStatus.PASSED.value,
                        ApplicationStatus.REJECTED.value,
                    ]),
                )
            )
            .distinct()
        ).subquery()

        query = select(Application).where(Application.id.in_(op_subq))

        count_q = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_q)).scalar() or 0

        query = (
            query.options(
                selectinload(Application.proofs),
                selectinload(Application.user),
            )
            .order_by(Application.updated_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await db.execute(query)
        return list(result.scalars().all()), total

    # ------------------------------------------------------------------
    # v4.3 新增：按审核员分流查询
    # ------------------------------------------------------------------
    @staticmethod
    async def list_pending_for_me(
        db: AsyncSession,
        reviewer_id: int,
        page: int = 1,
        size: int = 20,
        full_name: Optional[str] = None,
        student_id: Optional[str] = None,
        template_name: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> tuple[List[Application], int]:
        """当前审核员的待审核列表

        逻辑：status=APPLYING 且 reviewer_ids 不包含当前审核员
        支持高级搜索：full_name(姓名模糊)、student_id(从 username 前缀模糊)、template_name、
                      start_time/end_time(创建时间范围，ISO 字符串)
        """
        from sqlalchemy import literal_column

        contains_me = literal_column(
            f"reviewer_ids @> to_jsonb(ARRAY[{reviewer_id}])"
        )
        conditions = [
            Application.status == ApplicationStatus.APPLYING.value,
            or_(
                Application.reviewer_ids.is_(None),
                ~contains_me,
            ),
        ]

        # —— 高级搜索：必须 join user 才能用 full_name / student_id ——
        from sqlalchemy.orm import aliased
        from src.models.user import User
        user_alias = aliased(User)

        if full_name:
            conditions.append(user_alias.full_name.ilike(f"%{full_name}%"))
        if student_id:
            # username 形如 "33120...@stu.xmu.edu.cn"，用 username 前缀模糊匹配
            conditions.append(user_alias.username.ilike(f"{student_id}%"))
        if template_name:
            conditions.append(Application.template_name.ilike(f"%{template_name}%"))
        if start_time:
            conditions.append(Application.created_at >= start_time)
        if end_time:
            conditions.append(Application.created_at <= end_time)

        query = (
            select(Application)
            .join(user_alias, Application.user_id == user_alias.id)
            .where(*conditions)
            .options(
                selectinload(Application.proofs),
                selectinload(Application.user),
            )
            .order_by(Application.created_at.desc())
        )

        # count 时直接对 Application 表 count，避免子查询 + selectinload 的性能问题
        base_filter = select(Application.id).where(*conditions).subquery()
        count_q = select(func.count()).select_from(base_filter)
        total = (await db.execute(count_q)).scalar() or 0

        query = query.offset((page - 1) * size).limit(size)
        result = await db.execute(query)
        return list(result.scalars().all()), total

    @staticmethod
    async def list_my_reviewed(
        db: AsyncSession,
        reviewer_id: int,
        page: int = 1,
        size: int = 20,
        full_name: Optional[str] = None,
        student_id: Optional[str] = None,
        template_name: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        status: Optional[str] = None,
    ) -> tuple[List[Application], int]:
        """当前审核员的历史审核列表（reviewer_ids 包含自己）

        包含 PASSED / REJECTED 终态记录，按 updated_at 倒序。
        支持高级搜索：full_name / student_id / template_name / 时间范围 / status。
        """
        from sqlalchemy import literal_column

        contains_me = literal_column(
            f"reviewer_ids @> to_jsonb(ARRAY[{reviewer_id}])"
        )

        from sqlalchemy.orm import aliased
        from src.models.user import User
        user_alias = aliased(User)

        conditions = [contains_me]
        if full_name:
            conditions.append(user_alias.full_name.ilike(f"%{full_name}%"))
        if student_id:
            conditions.append(user_alias.username.ilike(f"{student_id}%"))
        if template_name:
            conditions.append(Application.template_name.ilike(f"%{template_name}%"))
        if status:
            conditions.append(Application.status == status)
        if start_time:
            conditions.append(Application.updated_at >= start_time)
        if end_time:
            conditions.append(Application.updated_at <= end_time)

        query = (
            select(Application)
            .join(user_alias, Application.user_id == user_alias.id)
            .where(*conditions)
            .options(
                selectinload(Application.proofs),
                selectinload(Application.user),
            )
            .order_by(Application.updated_at.desc())
        )

        base_filter = select(Application.id).where(*conditions).subquery()
        count_q = select(func.count()).select_from(base_filter)
        total = (await db.execute(count_q)).scalar() or 0

        query = query.offset((page - 1) * size).limit(size)
        result = await db.execute(query)
        return list(result.scalars().all()), total


# 兼容旧 service 名（保留给老代码调用——但语义已对齐 v4.2）
def get_application_status_text(status: str) -> str:
    return {
        ApplicationStatus.DRAFT.value: "草稿",
        ApplicationStatus.APPLYING.value: "审核中",
        ApplicationStatus.PASSED.value: "已通过",
        ApplicationStatus.REJECTED.value: "已驳回",
        ApplicationStatus.CANCELLED.value: "已取消",
        ApplicationStatus.REVOKED.value: "已撤回",
    }.get(status, "未知")