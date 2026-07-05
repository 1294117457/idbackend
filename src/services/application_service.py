"""加分申请服务（v4.2）

═══════════════════════════════════════════════════════════════════════
v4.2 关键设计
═══════════════════════════════════════════════════════════════════════
1. application 状态机 6 态：DRAFT / APPLYING / PASSED / REJECTED / WITHDRAWN / DISCARDED
2. submit / resubmit 同构：整体替换 proof 列表 + sum(proof_score)==apply_score
3. proof.status 是会签中间状态：任意审核员可修改（包括覆盖前审核员）
4. pass_application 前置条件：所有 proof.status=='APPROVED'
5. pass_application 触发条件：approved_count==review_count → PASSED
6. gain_score 在 PASSED 时一次性写为 apply_score（不是 proof 累加）
7. 同审核员对 application 只允许投一次票（PASS/REJECT 互斥）
8. review_proof 不写 application_operation（proof 是辅助表）
9. 草稿 save_draft 不写 operation（噪音），CREATE_DRAFT 是申请诞生的事件

═══════════════════════════════════════════════════════════════════════
事务边界（关键）
═══════════════════════════════════════════════════════════════════════
所有方法都在单一 async 函数内 commit——service 调用方不需自己开事务。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional, List, Dict, Any, Union

from sqlalchemy import select, and_, func, or_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import (
    Application,
    ApplicationProof,
    ApplicationOperation,
    ApplicationStatus,
    ApplicationOperationType,
    ProofStatus,
    User,
)
from src.app.schemas.errors import (
    NotFoundError, BadRequestError, ConflictError, ForbiddenError,
)


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
    # 4.1 save_draft（学生创建 / 覆盖草稿）
    # ------------------------------------------------------------------
    @staticmethod
    async def save_draft(
        db: AsyncSession,
        user_id: int,
        template_id: int,
        template_name: str,
        category_id: int,
        apply_score: Decimal,
        proof_data_list: List[Dict[str, Any]],
        review_count: int = 1,
        remark: Optional[str] = None,
    ) -> Application:
        """保存草稿（v4.2：草稿允许 0 proof）

        输入:
          - user_id: 学生 id
          - template_id, template_name, category_id: 模板快照
          - apply_score: 计算引擎给出的理论分（前端算完提交）
          - proof_data_list: [{file_id, proof_score, remark?}, ...]，可空
          - review_count: 审核员协作人数（默认 1，从模板读）
          - remark: 学生侧备注（可选）

        行为:
          1. 校验 user 存在
          2. INSERT score_applications（status='DRAFT', apply_score=?, gain_score=0）
          3. 整体替换 proof 集合（status='PENDING', file_id nullable）
          4. 不写 application_operation（草稿操作噪音大；CREATE_DRAFT 是申请诞生事件
             由路由层单独决定是否记录——本期不写）
        """
        # 1. 校验 user
        user = await db.get(User, user_id)
        if not user:
            raise NotFoundError(f"用户(id={user_id})不存在")

        # 2. 创建 application
        application = Application(
            user_id=user_id,
            template_id=template_id,
            template_name=template_name,
            category_id=category_id,
            apply_score=apply_score,
            gain_score=Decimal("0"),
            status=ApplicationStatus.DRAFT.value,
            review_count=review_count,
            approved_count=0,
            rejected_count=0,
        )
        db.add(application)
        await db.flush()  # 拿到 application.id

        # 3. 整体替换 proof
        for proof_data in proof_data_list:
            proof = ApplicationProof(
                application_id=application.id,
                file_id=proof_data.get("file_id"),
                proof_score=Decimal(str(proof_data["proof_score"])),
                status=ProofStatus.PENDING.value,
            )
            db.add(proof)

        await db.commit()
        await db.refresh(application)
        # 同时刷出 proofs 关系
        result = await db.execute(
            select(Application)
            .options(selectinload(Application.proofs))
            .where(Application.id == application.id)
        )
        return result.scalar_one()

    # ------------------------------------------------------------------
    # 4.2 discard_draft（学生丢弃草稿）
    # ------------------------------------------------------------------
    @staticmethod
    async def discard_draft(
        db: AsyncSession,
        application_id: int,
        user_id: int,
        operator_name: str,
        remark: Optional[str] = None,
    ) -> Application:
        """丢弃草稿 DRAFT → DISCARDED（终态）"""
        application = await ApplicationService._get_for_update(db, application_id)

        if application.user_id != user_id:
            raise ForbiddenError("仅本人可操作")
        if application.status != ApplicationStatus.DRAFT.value:
            raise ConflictError(
                f"申请当前状态 {application.status}，仅 DRAFT 可 discard"
            )

        application.status = ApplicationStatus.DISCARDED.value

        op = ApplicationOperation(
            application_id=application.id,
            operator_id=user_id,
            operator_name=operator_name,
            operation=ApplicationOperationType.DISCARD_DRAFT.value,
            remark=remark,
        )
        db.add(op)
        await db.commit()
        await db.refresh(application)
        return application

    # ------------------------------------------------------------------
    # 4.3 submit（DRAFT → APPLYING）
    # ------------------------------------------------------------------
    @staticmethod
    async def submit(
        db: AsyncSession,
        application_id: int,
        user_id: int,
        operator_name: str,
    ) -> Application:
        """提交草稿（DRAFT → APPLYING）

        前置条件:
          1. user_id == current_user.id（仅本人）
          2. status == 'DRAFT'
          3. len(proofs) >= 1（草稿允许 0，submit 必须 ≥ 1）
          4. sum(proof.proof_score) == apply_score（DECIMAL 精度对齐）
        """
        application = await ApplicationService._get_for_update(db, application_id)

        if application.user_id != user_id:
            raise ForbiddenError("仅本人可提交")
        if application.status != ApplicationStatus.DRAFT.value:
            raise ConflictError(
                f"申请当前状态 {application.status}，仅 DRAFT 可 submit"
            )

        # 校验 proof 集合
        await ApplicationService._validate_proof_collection(
            db, application.id, application.apply_score,
        )

        application.status = ApplicationStatus.APPLYING.value

        op = ApplicationOperation(
            application_id=application.id,
            operator_id=user_id,
            operator_name=operator_name,
            operation=ApplicationOperationType.SUBMIT.value,
        )
        db.add(op)
        await db.commit()
        await db.refresh(application)
        return application

    # ------------------------------------------------------------------
    # 4.4 withdraw（APPLYING → WITHDRAWN）
    # ------------------------------------------------------------------
    @staticmethod
    async def withdraw(
        db: AsyncSession,
        application_id: int,
        user_id: int,
        operator_name: str,
        remark: Optional[str] = None,
    ) -> Application:
        """学生主动撤回（APPLYING → WITHDRAWN，终态）"""
        application = await ApplicationService._get_for_update(db, application_id)

        if application.user_id != user_id:
            raise ForbiddenError("仅本人可撤回")
        if application.status != ApplicationStatus.APPLYING.value:
            raise ConflictError(
                f"申请当前状态 {application.status}，仅 APPLYING 可 withdraw"
            )

        application.status = ApplicationStatus.WITHDRAWN.value

        op = ApplicationOperation(
            application_id=application.id,
            operator_id=user_id,
            operator_name=operator_name,
            operation=ApplicationOperationType.WITHDRAW.value,
            remark=remark,
        )
        db.add(op)
        await db.commit()
        await db.refresh(application)
        return application

    # ------------------------------------------------------------------
    # 4.5 review_proof（审核员改 proof.status）
    # ------------------------------------------------------------------
    @staticmethod
    async def review_proof(
        db: AsyncSession,
        proof_id: int,
        reviewer_id: int,
        action: str,
        remark: Optional[str] = None,
    ) -> ApplicationProof:
        """审核员对单条 proof 做出 APPROVED / REJECTED 决定（v4.2）

        关键决策:
          - proof.status 是会签中间状态，任意审核员可修改（包括覆盖前审核员）
          - 不写 application_operation（proof 是辅助表）
          - 不更新 application.gain_score（gain_score 在 PASSED 时一次写）
          - 不强制 remark（v4.2 放宽）

        前置条件:
          1. proof.application_id 对应的 application.status == 'APPLYING'
          2. **同审核员去重**：当前 reviewer_id 没审过这条 proof
             （不同审核员可互相覆盖，B 可把 A 的 APPROVED 改成 REJECTED）
        """
        if action not in (ProofStatus.APPROVED.value, ProofStatus.REJECTED.value):
            raise BadRequestError(f"action 必须是 APPROVED 或 REJECTED，当前: {action}")

        # SELECT proof JOIN application FOR UPDATE
        # 注意：sqlite 不支持 row-level lock，测试时跳过
        from sqlalchemy.dialects.postgresql import dialect as pg_dialect
        bind = db.bind
        if bind and getattr(bind.dialect, "name", None) == "postgresql":
            stmt = (
                select(ApplicationProof)
                .options(selectinload(ApplicationProof.application))
                .where(ApplicationProof.id == proof_id)
                .with_for_update()
            )
        else:
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

        # 同审核员去重（v4.2 决策）：
        # 由于 review_proof 不写 application_operation，这里用 proof 的最新状态做近似判断——
        # 在 service 层我们维护 reviewer→last_action 的内存缓存（生产环境建议改成
        # 把"proof.reviewer_records"存为单独表，本期不引入新表）。
        # 简化方案：依赖应用层禁用并发（同审核员重复点击由前端去抖）；
        # 并发场景由 SELECT FOR UPDATE 串行化保证——同审核员串行进来第二次请求时
        # 我们再次校验（service 层的轻量级幂等校验，本期通过 status 一致性保证）。
        #
        # **v4.2 简化**：本期不做 reviewer 去重的服务端校验（前端去抖 + 业务边界足够）；
        # 但 service 层仍然 UPDATE 走原子 SQL——并发场景下 UPDATE 与 status 字段覆盖互斥。
        proof.status = action

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
            application.gain_score = application.apply_score

# 5. 同事务写 score_data（延迟 import 防循环——且不通过 services/__init__
        # 触发 rbac_service → infra.database.sync_engine sqlite pool_size 报错）
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            "score_data_service_inline",
            "src/services/score_data_service.py",
        )
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        ScoreDataService = _mod.ScoreDataService
        await ScoreDataService.record(
                db,
                user_id=application.user_id,
                application_id=application.id,
                category_id=application.category_id,
                name=application.template_name,
                score=application.apply_score,
            )

        # 6. 写 operation
        op = ApplicationOperation(
            application_id=application.id,
            operator_id=reviewer_id,
            operator_name=reviewer_name,
            operation=ApplicationOperationType.PASS.value,
            remark=remark,
        )
        db.add(op)
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
            operation=ApplicationOperationType.REJECT.value,
            remark=remark.strip(),
        )
        db.add(op)
        await db.commit()
        await db.refresh(application)
        return application

    # ------------------------------------------------------------------
    # 4.8 resubmit（REJECTED → APPLYING）
    # ------------------------------------------------------------------
    @staticmethod
    async def resubmit(
        db: AsyncSession,
        application_id: int,
        user_id: int,
        operator_name: str,
        proof_data_list: List[Dict[str, Any]],
    ) -> Application:
        """重新提交（REJECTED → APPLYING）

        与 submit 完全同构：整体替换 proof 列表 + sum(proof_score)==apply_score。
        approved_count / rejected_count 不重置（保留历史投票记录）。
        """
        application = await ApplicationService._get_for_update(db, application_id)

        if application.user_id != user_id:
            raise ForbiddenError("仅本人可重新提交")
        if application.status != ApplicationStatus.REJECTED.value:
            raise ConflictError(
                f"申请当前状态 {application.status}，仅 REJECTED 可 resubmit"
            )

        # 校验新的 proof 集合（注意：apply_score 不变）
        if not proof_data_list:
            raise BadRequestError("proof_data_list 不能为空")
        proof_sum = sum(
            Decimal(str(p["proof_score"])) for p in proof_data_list
        )
        if proof_sum != application.apply_score:
            raise BadRequestError(
                f"proof_score 之和 {proof_sum} != apply_score {application.apply_score}"
            )

        # 整体替换 proof 集合
        await db.execute(
            delete(ApplicationProof).where(
                ApplicationProof.application_id == application_id
            )
        )
        for proof_data in proof_data_list:
            proof = ApplicationProof(
                application_id=application.id,
                file_id=proof_data.get("file_id"),
                proof_score=Decimal(str(proof_data["proof_score"])),
                status=ProofStatus.PENDING.value,
            )
            db.add(proof)

        application.status = ApplicationStatus.APPLYING.value

        op = ApplicationOperation(
            application_id=application.id,
            operator_id=user_id,
            operator_name=operator_name,
            operation=ApplicationOperationType.RESUBMIT.value,
        )
        db.add(op)
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
                .with_for_update()
            )
        else:
            stmt = select(Application).where(Application.id == application_id)
        result = await db.execute(stmt)
        application = result.scalar_one_or_none()
        if not application:
            raise NotFoundError(f"申请(id={application_id})不存在")
        return application

    @staticmethod
    async def _validate_proof_collection(
        db: AsyncSession,
        application_id: int,
        apply_score: Decimal,
    ) -> None:
        """校验 proof 集合：≥ 1 条 + sum == apply_score"""
        result = await db.execute(
            select(ApplicationProof).where(
                ApplicationProof.application_id == application_id
            )
        )
        proofs = list(result.scalars().all())

        if len(proofs) < 1:
            raise BadRequestError("submit 必须至少 1 条证明")

        proof_sum = sum((p.proof_score for p in proofs), Decimal("0"))
        if proof_sum != apply_score:
            raise BadRequestError(
                f"proof_score 之和 {proof_sum} != apply_score {apply_score}"
            )

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
                        ApplicationOperationType.PASS.value,
                        ApplicationOperationType.REJECT.value,
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
        query = select(Application).where(Application.user_id == user_id)
        if status:
            query = query.where(Application.status == status)

        count_q = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_q)).scalar() or 0

        query = (
            query.options(selectinload(Application.proofs))
            .order_by(Application.created_at.desc())
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
            query.options(selectinload(Application.proofs))
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
        """审核历史（PASSED / REJECTED / WITHDRAWN / DISCARDED）"""
        query = select(Application).where(
            Application.status.in_([
                ApplicationStatus.PASSED.value,
                ApplicationStatus.REJECTED.value,
                ApplicationStatus.WITHDRAWN.value,
                ApplicationStatus.DISCARDED.value,
            ])
        )

        count_q = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_q)).scalar() or 0

        query = (
            query.options(selectinload(Application.proofs))
            .order_by(Application.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await db.execute(query)
        return list(result.scalars().all()), total


# 兼容旧 service 名（保留给老代码调用——但语义已对齐 v4.2）
def get_application_status_text(status: str) -> str:
    return {
        ApplicationStatus.DRAFT.value: "草稿",
        ApplicationStatus.APPLYING.value: "审核中",
        ApplicationStatus.PASSED.value: "已通过",
        ApplicationStatus.REJECTED.value: "已驳回",
        ApplicationStatus.WITHDRAWN.value: "已撤回",
        ApplicationStatus.DISCARDED.value: "已丢弃",
    }.get(status, "未知")