"""ScoreDataService 单元测试（v4.2）

测试场景：
  1. record 写 score_data 行（gain_score = apply_score 快照）
  2. recalculate 叶子聚合 → 封顶 → 写 user.score_info
  3. recalculate 嵌套分类树封顶（多层）
  4. get_summary 命中 user.score_info 缓存
  5. get_summary 未命中 → 兜底 recalculate
"""
import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import asyncio
from decimal import Decimal

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from src.models import Base
from src.models.user import User
from src.models.template_category import TemplateCategory

# 直接 import 绕过 services/__init__.py 触发 rbac_service → infra.database
import importlib.util


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_score_data_mod = _load("score_data_service_test", "src/services/score_data_service.py")
ScoreDataService = _score_data_mod.ScoreDataService


def assert_eq(actual, expected, msg: str = ""):
    if actual != expected:
        raise AssertionError(f"{msg} expected={expected!r} actual={actual!r}")


async def _setup():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, Session()


async def _make_tree(db):
    """构造测试分类树：
        加分总计(max=100)
          └── 加分(max=80)
                ├── 学业(max=60)
                │     ├── 竞赛(raw=25, max=20)
                │     └── 论文(raw=15, max=10)
                └── 专长(max=30)
                      └── 体育(raw=35, max=30)
    """
    root = TemplateCategory(name="加分总计", max_score=Decimal("100"), is_active=True)
    db.add(root); await db.flush()
    sub = TemplateCategory(name="加分", parent_id=root.id, max_score=Decimal("80"), is_active=True)
    db.add(sub); await db.flush()
    aca = TemplateCategory(name="学业", parent_id=sub.id, max_score=Decimal("60"), is_active=True)
    db.add(aca); await db.flush()
    spec = TemplateCategory(name="专长", parent_id=sub.id, max_score=Decimal("30"), is_active=True)
    db.add(spec); await db.flush()
    jingsai = TemplateCategory(name="竞赛", parent_id=aca.id, max_score=Decimal("20"), is_active=True)
    lunwen = TemplateCategory(name="论文", parent_id=aca.id, max_score=Decimal("10"), is_active=True)
    tiyu = TemplateCategory(name="体育", parent_id=spec.id, max_score=Decimal("30"), is_active=True)
    db.add_all([jingsai, lunwen, tiyu]); await db.flush()
    await db.commit()
    return {
        "root": root, "sub": sub, "aca": aca, "spec": spec,
        "jingsai": jingsai, "lunwen": lunwen, "tiyu": tiyu,
    }


# ============================================================
# 测试 1：record 写流水
# ============================================================
async def case_record_writes_score_data():
    engine, db = await _setup()
    try:
        tree = await _make_tree(db)
        student = User(username="s1", password="x", full_name="张三", is_confirmed=True)
        db.add(student); await db.flush()

        from src.models.application import Application, ApplicationStatus
        app = Application(
            user_id=student.id, template_id=1, template_name="t",
            category_id=tree["jingsai"].id, apply_score=Decimal("5.0"),
            gain_score=Decimal("0"), status=ApplicationStatus.PASSED.value,
            review_count=1, approved_count=1, rejected_count=0,
        )
        db.add(app); await db.flush(); await db.commit()

        score_data = await ScoreDataService.record(
            db,
            user_id=student.id,
            application_id=app.id,
            category_id=tree["jingsai"].id,
            name="竞赛奖项",
            score=Decimal("5.0"),
        )
        assert_eq(score_data.user_id, student.id, "user_id")
        assert_eq(score_data.application_id, app.id, "application_id")
        assert_eq(score_data.score, Decimal("5.0"), "score")
        assert_eq(score_data.is_active, True, "is_active")
        print("  ✓ case_record_writes_score_data")
    finally:
        await db.close()
        await engine.dispose()


# ============================================================
# 测试 2：recalculate 叶子聚合 → 封顶 → 写 user.score_info
# ============================================================
async def case_recalculate_caps_leaves():
    engine, db = await _setup()
    try:
        tree = await _make_tree(db)
        student = User(username="s2", password="x", full_name="李四", is_confirmed=True)
        db.add(student); await db.flush()

        from src.models.application import Application, ApplicationStatus
        # 写 4 条流水：竞赛 raw=25, 论文 raw=15, 体育 raw=35
        apps_data = [
            (tree["jingsai"].id, "竞赛", Decimal("25.0")),
            (tree["lunwen"].id, "论文", Decimal("15.0")),
            (tree["tiyu"].id, "体育", Decimal("35.0")),
        ]
        for cid, name, score in apps_data:
            app = Application(
                user_id=student.id, template_id=1, template_name=name,
                category_id=cid, apply_score=score, gain_score=score,
                status=ApplicationStatus.PASSED.value,
                review_count=1, approved_count=1, rejected_count=0,
            )
            db.add(app); await db.flush()
            await ScoreDataService.record(
                db, user_id=student.id, application_id=app.id,
                category_id=cid, name=name, score=score,
            )
        await db.commit()

        # 触发 recalculate
        score_info = await ScoreDataService.recalculate(db, student.id)

        # 预期封顶：竞赛 capped=20, 论文 capped=10, 体育 capped=30
        # 学业 = min(20+10, 60) = 30
        # 专长 = min(30, 30) = 30
        # 加分 = min(30+30, 80) = 60
        # 加分总计 = min(60, 100) = 60
        cats = score_info["categories"]
        assert_eq(cats[str(tree["jingsai"].id)]["score"], 20.0, "jingsai capped")
        assert_eq(cats[str(tree["lunwen"].id)]["score"], 10.0, "lunwen capped")
        assert_eq(cats[str(tree["tiyu"].id)]["score"], 30.0, "tiyu capped")
        assert_eq(cats[str(tree["aca"].id)]["score"], 30.0, "aca sum")
        assert_eq(cats[str(tree["spec"].id)]["score"], 30.0, "spec sum")
        assert_eq(cats[str(tree["sub"].id)]["score"], 60.0, "sub sum")
        assert_eq(score_info["total"], 60.0, "total")
        print("  ✓ case_recalculate_caps_leaves")
    finally:
        await db.close()
        await engine.dispose()


# ============================================================
# 测试 3：get_summary 命中缓存
# ============================================================
async def case_get_summary_hit_cache():
    engine, db = await _setup()
    try:
        tree = await _make_tree(db)
        student = User(username="s3", password="x", full_name="王五", is_confirmed=True)
        db.add(student); await db.flush()

        from src.models.application import Application, ApplicationStatus
        app = Application(
            user_id=student.id, template_id=1, template_name="t",
            category_id=tree["tiyu"].id, apply_score=Decimal("10"),
            gain_score=Decimal("10"), status=ApplicationStatus.PASSED.value,
            review_count=1, approved_count=1, rejected_count=0,
        )
        db.add(app); await db.flush()
        await ScoreDataService.record(
            db, user_id=student.id, application_id=app.id,
            category_id=tree["tiyu"].id, name="体育", score=Decimal("10"),
        )
        await db.commit()

        # 先 recalculate 写 score_info（含 categories）
        await ScoreDataService.recalculate(db, student.id)

        # 再调 get_summary 应该命中
        result = await ScoreDataService.get_summary(db, student.id)
        assert_eq(result["hit"], True, "hit")
        assert "score_info" in result, "score_info present"
        assert str(tree["tiyu"].id) in result["score_info"]["categories"], "categories 包含 tiyu"
        print("  ✓ case_get_summary_hit_cache")
    finally:
        await db.close()
        await engine.dispose()


# ============================================================
# 测试 4：get_summary 未命中 → 兜底 recalculate
# ============================================================
async def case_get_summary_miss_fallback():
    engine, db = await _setup()
    try:
        tree = await _make_tree(db)
        student = User(username="s4", password="x", full_name="赵六", is_confirmed=True)
        db.add(student); await db.flush()

        from src.models.application import Application, ApplicationStatus
        app = Application(
            user_id=student.id, template_id=1, template_name="t",
            category_id=tree["tiyu"].id, apply_score=Decimal("10"),
            gain_score=Decimal("10"), status=ApplicationStatus.PASSED.value,
            review_count=1, approved_count=1, rejected_count=0,
        )
        db.add(app); await db.flush()
        await ScoreDataService.record(
            db, user_id=student.id, application_id=app.id,
            category_id=tree["tiyu"].id, name="体育", score=Decimal("10"),
        )
        await db.commit()

        # get_summary 未命中 → 兜底 recalculate
        result = await ScoreDataService.get_summary(db, student.id)
        assert_eq(result["hit"], False, "miss → recalculate")
        cats = result["score_info"]["categories"]
        assert_eq(cats[str(tree["tiyu"].id)]["score"], 10.0, "tiyu")
        print("  ✓ case_get_summary_miss_fallback")
    finally:
        await db.close()
        await engine.dispose()


# ============================================================
# 入口
# ============================================================
async def main():
    print("=" * 70)
    print("ScoreDataService v4.2 单元测试")
    print("=" * 70)

    cases = [
        case_record_writes_score_data,
        case_recalculate_caps_leaves,
        case_get_summary_hit_cache,
        case_get_summary_miss_fallback,
    ]

    passed = 0
    failed = 0
    for case in cases:
        try:
            await case()
            passed += 1
        except Exception as e:
            import traceback
            failed += 1
            print(f"  ✗ {case.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()

    print()
    print("=" * 70)
    print(f"结果：{passed}/{len(cases)} 通过，{failed} 失败")
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))