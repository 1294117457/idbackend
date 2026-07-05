"""ApplicationService 单元测试（v4.2）— 直接 asyncio.run 避免 pytest-asyncio fixture 兼容问题"""
import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import asyncio
from decimal import Decimal

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

# === 关键：测试场景下完全绕过 src.infra.database（避免 pool_size 错误）===
# 独立构建 sqlite 内存引擎 + 独立 session，不依赖 rbac_service / settings
from src.models import Base
from src.models.user import User
from src.models.template import Template
from src.models.template_category import TemplateCategory
from src.models import ProofStatus
from src.app.schemas.errors import BadRequestError, ConflictError

# === 直接 import ApplicationService（service 内部不用 db 全局对象）===
import importlib.util
spec = importlib.util.spec_from_file_location(
    "application_service_test", "src/services/application_service.py"
)
asm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(asm)
ApplicationService = asm.ApplicationService


# ============================================================
# 测试基础设施
# ============================================================
async def _setup_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, Session()


async def _seed_data(db_session):
    category = TemplateCategory(
        name="学业", max_score=Decimal("60"), is_active=True, is_bind_template=True,
    )
    db_session.add(category)
    await db_session.flush()

    template = Template(
        name="竞赛奖项",
        category_id=category.id,
        max_score=Decimal("20"),
        review_count=1,    # 默认 1；多审核员场景在 case 里改
        is_active=True,
    )
    db_session.add(template)
    await db_session.flush()

    student = User(username="student1", password="x", full_name="张三", is_confirmed=True)
    student2 = User(username="student2", password="x", full_name="李四", is_confirmed=True)
    reviewer_a = User(username="reviewer_a", password="x", full_name="王老师", is_confirmed=True)
    reviewer_b = User(username="reviewer_b", password="x", full_name="赵老师", is_confirmed=True)
    db_session.add_all([student, student2, reviewer_a, reviewer_b])
    await db_session.flush()
    await db_session.commit()

    return {
        "category": category, "template": template,
        "student": student, "student2": student2,
        "reviewer_a": reviewer_a, "reviewer_b": reviewer_b,
    }


def assert_eq(actual, expected, msg: str = ""):
    if actual != expected:
        raise AssertionError(f"{msg} expected={expected!r} actual={actual!r}")


# ============================================================
# 单条测试用例
# ============================================================
async def case_save_draft_allows_zero_proofs():
    engine, db = await _setup_session()
    try:
        s = await _seed_data(db)
        app = await ApplicationService.save_draft(
            db, user_id=s["student"].id, template_id=s["template"].id,
            template_name=s["template"].name, category_id=s["category"].id,
            apply_score=Decimal("5.0"), proof_data_list=[],
        )
        assert_eq(app.status, "DRAFT", "status")
        assert_eq(len(app.proofs), 0, "proofs count")
        assert_eq(app.apply_score, Decimal("5.0"), "apply_score")
        print("  ✓ test_save_draft_allows_zero_proofs")
    finally:
        await db.close()
        await engine.dispose()


async def case_submit_requires_proof_sum_match():
    engine, db = await _setup_session()
    try:
        s = await _seed_data(db)
        app = await ApplicationService.save_draft(
            db, user_id=s["student"].id, template_id=s["template"].id,
            template_name=s["template"].name, category_id=s["category"].id,
            apply_score=Decimal("5.0"),
            proof_data_list=[
                {"file_id": None, "proof_score": 3.0},
                {"file_id": None, "proof_score": 2.0},
            ],
        )
        submitted = await ApplicationService.submit(db, app.id, s["student"].id, "张三")
        assert_eq(submitted.status, "APPLYING", "status")
        print("  ✓ test_submit_requires_proof_sum_match")
    finally:
        await db.close()
        await engine.dispose()


async def case_submit_zero_proof_fails():
    engine, db = await _setup_session()
    try:
        s = await _seed_data(db)
        app = await ApplicationService.save_draft(
            db, user_id=s["student"].id, template_id=s["template"].id,
            template_name=s["template"].name, category_id=s["category"].id,
            apply_score=Decimal("5.0"), proof_data_list=[],
        )
        try:
            await ApplicationService.submit(db, app.id, s["student"].id, "张三")
            raise AssertionError("expected BadRequestError")
        except BadRequestError:
            print("  ✓ test_submit_zero_proof_fails")
    finally:
        await db.close()
        await engine.dispose()


async def case_review_proof_overwrite():
    engine, db = await _setup_session()
    try:
        s = await _seed_data(db)
        app = await ApplicationService.save_draft(
            db, user_id=s["student"].id, template_id=s["template"].id,
            template_name=s["template"].name, category_id=s["category"].id,
            apply_score=Decimal("5.0"),
            proof_data_list=[{"file_id": None, "proof_score": 5.0}],
        )
        await ApplicationService.submit(db, app.id, s["student"].id, "张三")
        app_full = await ApplicationService.get_by_id(db, app.id)
        proof_id = app_full.proofs[0].id

        proof1 = await ApplicationService.review_proof(
            db, proof_id=proof_id, reviewer_id=s["reviewer_a"].id,
            action=ProofStatus.APPROVED.value,
        )
        assert_eq(proof1.status, "APPROVED", "after A")

        proof2 = await ApplicationService.review_proof(
            db, proof_id=proof_id, reviewer_id=s["reviewer_b"].id,
            action=ProofStatus.REJECTED.value,
        )
        assert_eq(proof2.status, "REJECTED", "after B overwrite")
        print("  ✓ test_review_proof_overwrite")
    finally:
        await db.close()
        await engine.dispose()


async def case_pass_application_review_count_1():
    engine, db = await _setup_session()
    try:
        s = await _seed_data(db)
        s["template"].review_count = 1
        await db.commit()

        app = await ApplicationService.save_draft(
            db, user_id=s["student"].id, template_id=s["template"].id,
            template_name=s["template"].name, category_id=s["category"].id,
            apply_score=Decimal("5.0"),
            proof_data_list=[{"file_id": None, "proof_score": 5.0}],
        )
        await ApplicationService.submit(db, app.id, s["student"].id, "张三")
        app_full = await ApplicationService.get_by_id(db, app.id)
        await ApplicationService.review_proof(
            db, app_full.proofs[0].id, s["reviewer_a"].id, ProofStatus.APPROVED.value,
        )
        passed = await ApplicationService.pass_application(
            db, application_id=app.id, reviewer_id=s["reviewer_a"].id,
            reviewer_name="王老师",
        )
        assert_eq(passed.status, "PASSED", "status")
        assert_eq(passed.approved_count, 1, "approved_count")
        assert_eq(passed.gain_score, Decimal("5.0"), "gain_score")
        print("  ✓ test_pass_application_review_count_1")
    finally:
        await db.close()
        await engine.dispose()


async def case_pass_application_review_count_2():
    engine, db = await _setup_session()
    try:
        s = await _seed_data(db)
        # review_count=2：模板改 + application 跟着改
        s["template"].review_count = 2
        await db.commit()
        app = await ApplicationService.save_draft(
            db, user_id=s["student"].id, template_id=s["template"].id,
            template_name=s["template"].name, category_id=s["category"].id,
            apply_score=Decimal("5.0"),
            proof_data_list=[{"file_id": None, "proof_score": 5.0}],
            review_count=2,
        )
        await ApplicationService.submit(db, app.id, s["student"].id, "张三")
        app_full = await ApplicationService.get_by_id(db, app.id)
        await ApplicationService.review_proof(
            db, app_full.proofs[0].id, s["reviewer_a"].id, ProofStatus.APPROVED.value,
        )

        after_a = await ApplicationService.pass_application(
            db, app.id, s["reviewer_a"].id, "王老师",
        )
        assert_eq(after_a.status, "APPLYING", "after A")
        assert_eq(after_a.approved_count, 1, "approved_count after A")

        after_b = await ApplicationService.pass_application(
            db, app.id, s["reviewer_b"].id, "赵老师",
        )
        assert_eq(after_b.status, "PASSED", "after B")
        assert_eq(after_b.approved_count, 2, "approved_count after B")
        assert_eq(after_b.gain_score, Decimal("5.0"), "gain_score")
        print("  ✓ test_pass_application_review_count_2")
    finally:
        await db.close()
        await engine.dispose()


async def case_pass_application_fails_when_pending_proof():
    engine, db = await _setup_session()
    try:
        s = await _seed_data(db)
        app = await ApplicationService.save_draft(
            db, user_id=s["student"].id, template_id=s["template"].id,
            template_name=s["template"].name, category_id=s["category"].id,
            apply_score=Decimal("5.0"),
            proof_data_list=[{"file_id": None, "proof_score": 5.0}],
        )
        await ApplicationService.submit(db, app.id, s["student"].id, "张三")
        try:
            await ApplicationService.pass_application(
                db, app.id, s["reviewer_a"].id, "王老师",
            )
            raise AssertionError("expected ConflictError")
        except ConflictError:
            print("  ✓ test_pass_application_fails_when_pending_proof")
    finally:
        await db.close()
        await engine.dispose()


async def case_reject_application_veto():
    engine, db = await _setup_session()
    try:
        s = await _seed_data(db)
        app = await ApplicationService.save_draft(
            db, user_id=s["student"].id, template_id=s["template"].id,
            template_name=s["template"].name, category_id=s["category"].id,
            apply_score=Decimal("5.0"),
            proof_data_list=[{"file_id": None, "proof_score": 5.0}],
        )
        await ApplicationService.submit(db, app.id, s["student"].id, "张三")
        rejected = await ApplicationService.reject_application(
            db, app.id, s["reviewer_a"].id, "王老师", "材料不清晰",
        )
        assert_eq(rejected.status, "REJECTED", "status")
        assert_eq(rejected.rejected_count, 1, "rejected_count")
        print("  ✓ test_reject_application_veto")
    finally:
        await db.close()
        await engine.dispose()


async def case_reject_requires_remark():
    engine, db = await _setup_session()
    try:
        s = await _seed_data(db)
        app = await ApplicationService.save_draft(
            db, user_id=s["student"].id, template_id=s["template"].id,
            template_name=s["template"].name, category_id=s["category"].id,
            apply_score=Decimal("5.0"),
            proof_data_list=[{"file_id": None, "proof_score": 5.0}],
        )
        await ApplicationService.submit(db, app.id, s["student"].id, "张三")
        try:
            await ApplicationService.reject_application(
                db, app.id, s["reviewer_a"].id, "王老师", "   ",
            )
            raise AssertionError("expected BadRequestError")
        except BadRequestError:
            print("  ✓ test_reject_requires_remark")
    finally:
        await db.close()
        await engine.dispose()


async def case_resubmit_after_rejected():
    engine, db = await _setup_session()
    try:
        s = await _seed_data(db)
        app = await ApplicationService.save_draft(
            db, user_id=s["student"].id, template_id=s["template"].id,
            template_name=s["template"].name, category_id=s["category"].id,
            apply_score=Decimal("5.0"),
            proof_data_list=[{"file_id": None, "proof_score": 5.0}],
        )
        await ApplicationService.submit(db, app.id, s["student"].id, "张三")
        await ApplicationService.reject_application(
            db, app.id, s["reviewer_a"].id, "王老师", "材料不清晰",
        )
        resubmitted = await ApplicationService.resubmit(
            db, application_id=app.id, user_id=s["student"].id,
            operator_name="张三",
            proof_data_list=[
                {"file_id": None, "proof_score": 3.0},
                {"file_id": None, "proof_score": 2.0},
            ],
        )
        assert_eq(resubmitted.status, "APPLYING", "status")
        assert_eq(len(resubmitted.proofs), 2, "proofs count")
        print("  ✓ test_resubmit_after_rejected")
    finally:
        await db.close()
        await engine.dispose()


async def case_withdraw_from_applying():
    engine, db = await _setup_session()
    try:
        s = await _seed_data(db)
        app = await ApplicationService.save_draft(
            db, user_id=s["student"].id, template_id=s["template"].id,
            template_name=s["template"].name, category_id=s["category"].id,
            apply_score=Decimal("5.0"),
            proof_data_list=[{"file_id": None, "proof_score": 5.0}],
        )
        await ApplicationService.submit(db, app.id, s["student"].id, "张三")
        withdrawn = await ApplicationService.withdraw(
            db, app.id, s["student"].id, "张三",
        )
        assert_eq(withdrawn.status, "WITHDRAWN", "status")
        print("  ✓ test_withdraw_from_applying")
    finally:
        await db.close()
        await engine.dispose()


async def case_discard_draft():
    engine, db = await _setup_session()
    try:
        s = await _seed_data(db)
        app = await ApplicationService.save_draft(
            db, user_id=s["student"].id, template_id=s["template"].id,
            template_name=s["template"].name, category_id=s["category"].id,
            apply_score=Decimal("5.0"), proof_data_list=[],
        )
        discarded = await ApplicationService.discard_draft(
            db, app.id, s["student"].id, "张三",
        )
        assert_eq(discarded.status, "DISCARDED", "status")
        print("  ✓ test_discard_draft")
    finally:
        await db.close()
        await engine.dispose()


async def case_gain_score_only_on_passed():
    engine, db = await _setup_session()
    try:
        s = await _seed_data(db)
        s["template"].review_count = 1
        await db.commit()
        app = await ApplicationService.save_draft(
            db, user_id=s["student"].id, template_id=s["template"].id,
            template_name=s["template"].name, category_id=s["category"].id,
            apply_score=Decimal("5.0"),
            proof_data_list=[{"file_id": None, "proof_score": 5.0}],
        )
        await ApplicationService.submit(db, app.id, s["student"].id, "张三")
        app_full = await ApplicationService.get_by_id(db, app.id)
        await ApplicationService.review_proof(
            db, app_full.proofs[0].id, s["reviewer_a"].id, ProofStatus.APPROVED.value,
        )
        refreshed = await ApplicationService.get_by_id(db, app.id)
        assert_eq(refreshed.gain_score, Decimal("0"), "gain_score before pass")
        passed = await ApplicationService.pass_application(
            db, app.id, s["reviewer_a"].id, "王老师",
        )
        assert_eq(passed.gain_score, Decimal("5.0"), "gain_score after pass")
        print("  ✓ test_gain_score_only_on_passed")
    finally:
        await db.close()
        await engine.dispose()


async def case_same_reviewer_cannot_vote_twice():
    engine, db = await _setup_session()
    try:
        s = await _seed_data(db)
        app = await ApplicationService.save_draft(
            db, user_id=s["student"].id, template_id=s["template"].id,
            template_name=s["template"].name, category_id=s["category"].id,
            apply_score=Decimal("5.0"),
            proof_data_list=[{"file_id": None, "proof_score": 5.0}],
        )
        await ApplicationService.submit(db, app.id, s["student"].id, "张三")
        app_full = await ApplicationService.get_by_id(db, app.id)
        await ApplicationService.review_proof(
            db, app_full.proofs[0].id, s["reviewer_a"].id, ProofStatus.APPROVED.value,
        )
        await ApplicationService.pass_application(
            db, app.id, s["reviewer_a"].id, "王老师",
        )
        try:
            await ApplicationService.pass_application(
                db, app.id, s["reviewer_a"].id, "王老师",
            )
            raise AssertionError("expected ConflictError")
        except ConflictError:
            print("  ✓ test_same_reviewer_cannot_vote_twice")
    finally:
        await db.close()
        await engine.dispose()


async def case_veto_scenario_full_flow():
    """review_count=2：A 投 PASS 后 B 把 proof REJECTED → B 投 application REJECTED"""
    engine, db = await _setup_session()
    try:
        s = await _seed_data(db)
        s["template"].review_count = 2
        await db.commit()
        app = await ApplicationService.save_draft(
            db, user_id=s["student"].id, template_id=s["template"].id,
            template_name=s["template"].name, category_id=s["category"].id,
            apply_score=Decimal("5.0"),
            proof_data_list=[{"file_id": None, "proof_score": 5.0}],
            review_count=2,
        )
        await ApplicationService.submit(db, app.id, s["student"].id, "张三")
        app_full = await ApplicationService.get_by_id(db, app.id)
        proof_id = app_full.proofs[0].id

        # A 审 proof + 投 PASS
        await ApplicationService.review_proof(
            db, proof_id, s["reviewer_a"].id, ProofStatus.APPROVED.value,
        )
        after_a = await ApplicationService.pass_application(
            db, app.id, s["reviewer_a"].id, "王老师",
        )
        assert_eq(after_a.status, "APPLYING", "after A pass")
        assert_eq(after_a.approved_count, 1, "approved_count after A")

        # B 把 proof 从 APPROVED 改成 REJECTED（veto）
        await ApplicationService.review_proof(
            db, proof_id, s["reviewer_b"].id, ProofStatus.REJECTED.value,
        )

        # B 试图投 PASS → 失败（proof 不是 APPROVED）
        try:
            await ApplicationService.pass_application(
                db, app.id, s["reviewer_b"].id, "赵老师",
            )
            raise AssertionError("expected ConflictError on B pass attempt")
        except ConflictError:
            pass

        # B 改投 REJECTED → application REJECTED
        after_b_reject = await ApplicationService.reject_application(
            db, app.id, s["reviewer_b"].id, "赵老师", "材料有问题",
        )
        assert_eq(after_b_reject.status, "REJECTED", "after B reject")
        assert_eq(after_b_reject.rejected_count, 1, "rejected_count after B")
        print("  ✓ test_veto_scenario_full_flow")
    finally:
        await db.close()
        await engine.dispose()


# ============================================================
# 入口
# ============================================================
async def main():
    print("=" * 70)
    print("ApplicationService v4.2 单元测试")
    print("=" * 70)

    cases = [
        case_save_draft_allows_zero_proofs,
        case_submit_requires_proof_sum_match,
        case_submit_zero_proof_fails,
        case_review_proof_overwrite,
        case_pass_application_review_count_1,
        case_pass_application_review_count_2,
        case_pass_application_fails_when_pending_proof,
        case_reject_application_veto,
        case_reject_requires_remark,
        case_resubmit_after_rejected,
        case_withdraw_from_applying,
        case_discard_draft,
        case_gain_score_only_on_passed,
        case_same_reviewer_cannot_vote_twice,
        case_veto_scenario_full_flow,
    ]

    passed = 0
    failed = 0
    for case in cases:
        try:
            await case()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  ✗ {case.__name__}: {type(e).__name__}: {e}")

    print()
    print("=" * 70)
    print(f"结果：{passed}/{len(cases)} 通过，{failed} 失败")
    print("=" * 70)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))