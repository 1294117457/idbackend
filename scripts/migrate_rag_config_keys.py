"""system_config 表 RAG 字段重构脚本

把过时的 RRF / source_discount / bm25_rank1_weight / hybrid_weight / search_mode
替换为新的"召回参数 + 融合权重"两段式字段。

新字段（与 src.infra.config.Settings、src.app.schemas.system_config.RagConfigKeys 对齐）
  召回参数：
    - RAG_TOP_K              (int)   最终返回条数          默认 5
    - RAG_CANDIDATE_K        (int)   候选池大小（0=自动）  默认 0
    - RAG_MIN_SCORE          (float) 融合后最低分门槛      默认 0.05
  融合权重：
    - RAG_VECTOR_WEIGHT          (float) 向量路权重        默认 1.0
    - RAG_BM25_WEIGHT            (float) BM25 路权重       默认 1.0
    - RAG_SINGLE_SOURCE_PENALTY  (float) 单路命中折扣      默认 0.5
    - RAG_SAME_DOC_DECAY         (float) 同文档第 n 衰减   默认 0.7

物理模型不变（仍是 system_config KV 表），仅清理 / 插入配置项。

用法（服务器上）：
  cd /home/dustp/codes/idproject/idbackend
  python3 scripts/migrate_rag_config_keys.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.infra.config import get_async_database_url


# 旧 config_key → 新 config_key 映射（仅展示用，脚本按列表操作）
OBSOLETE_KEYS = [
    "RAG_SEARCH_MODE",
    "RAG_RRF_K",
    "RAG_SOURCE_DISCOUNT",
    "RAG_BM25_RANK1_WEIGHT",
    "RAG_HYBRID_WEIGHT",
]

# 新字段：(config_key, default_value, value_type, description)
NEW_KEYS = [
    # 召回参数
    ("RAG_TOP_K",               "5",   "int",   "RAG 检索：最终返回条数"),
    ("RAG_CANDIDATE_K",         "0",   "int",   "RAG 检索：候选池大小（0=自动）"),
    ("RAG_MIN_SCORE",           "0.05","float", "RAG 检索：融合后最低分门槛"),
    # 融合权重
    ("RAG_VECTOR_WEIGHT",       "1.0", "float", "RAG 检索：向量路权重"),
    ("RAG_BM25_WEIGHT",         "1.0", "float", "RAG 检索：BM25 路权重"),
    ("RAG_SINGLE_SOURCE_PENALTY","0.5","float", "RAG 检索：单路命中折扣"),
    ("RAG_SAME_DOC_DECAY",      "0.7", "float", "RAG 检索：同文档第 n 衰减系数"),
]


async def main():
    url = get_async_database_url()
    print(f"🔗 连接: {url}\n")

    engine = create_async_engine(url, echo=False)

    async with engine.begin() as conn:
        # ── 前置检查：表是否存在 ────────────────────────────────────
        result = await conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_name = 'system_config' AND table_schema = 'public';
        """))
        if not result.scalar_one():
            print("❌ system_config 表不存在，请先初始化数据库")
            await engine.dispose()
            return

        # ── 现有 RAG 相关行 ─────────────────────────────────────────
        print("=" * 60)
        print("🔍 当前 RAG 相关配置")
        print("=" * 60)
        result = await conn.execute(text("""
            SELECT config_key, config_value, value_type, description
            FROM system_config
            WHERE config_key LIKE 'RAG_%'
            ORDER BY config_key;
        """))
        rows = result.fetchall()
        if not rows:
            print("  (无 RAG_* 配置)")
        else:
            for r in rows:
                print(f"  {r.config_key:<30} {r.config_value:<10} ({r.value_type})")

        # ── 确认执行 ────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("⚠️  即将执行的操作")
        print("=" * 60)
        print(f"  1. 删除 {len(OBSOLETE_KEYS)} 个旧字段：")
        for k in OBSOLETE_KEYS:
            print(f"     - {k}")
        print(f"\n  2. 插入 {len(NEW_KEYS)} 个新字段（已存在则跳过，保留 DB 里的值）")
        print("     （注意：旧 key 删除后，DB 里调过的值不会自动迁移到新 key）")

        print("\n回滚 SQL（如需）：")
        print("  -- 把 RAG_TOP_K / RAG_CANDIDATE_K 重新插入旧 key 对应的值")
        print("  -- （新字段语义与旧字段不完全一一对应，需人工评估）\n")

        answer = input("确认执行？[yes/N]: ").strip().lower()
        if answer not in ("yes", "y"):
            print("❌ 已取消")
            await engine.dispose()
            return

        # ── 1. 删除旧字段 ───────────────────────────────────────────
        print("\n" + "=" * 60)
        print("🗑️  删除旧字段")
        print("=" * 60)
        for key in OBSOLETE_KEYS:
            result = await conn.execute(
                text("DELETE FROM system_config WHERE config_key = :k;"),
                {"k": key},
            )
            if result.rowcount:
                print(f"  ✅ 已删除: {key}")
            else:
                print(f"  ⏭️  不存在:  {key}")

        # ── 2. 插入新字段 ───────────────────────────────────────────
        print("\n" + "=" * 60)
        print("📦 插入新字段")
        print("=" * 60)
        for key, default_val, vtype, desc in NEW_KEYS:
            # 存在则跳过（ON CONFLICT DO NOTHING 幂等）
            result = await conn.execute(
                text("""
                    INSERT INTO system_config
                        (config_key, config_value, category, value_type, description, is_sensitive,
                         created_at, updated_at)
                    VALUES
                        (:k, :v, 'RAG', :vt, :d, false,
                         NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC')
                    ON CONFLICT (config_key) DO NOTHING
                    RETURNING config_key;
                """),
                {"k": key, "v": default_val, "vt": vtype, "d": desc},
            )
            inserted = result.scalar_one_or_none()
            if inserted:
                print(f"  ✅ 已插入: {inserted:<32} = {default_val} ({vtype})")
            else:
                # 查一下现有值
                result = await conn.execute(
                    text("SELECT config_value FROM system_config WHERE config_key = :k;"),
                    {"k": key},
                )
                cur = result.scalar_one()
                print(f"  ⏭️  已存在: {key:<32} 当前值={cur} (保留)")

        # ── 验证 ────────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("📋 验证：RAG 配置现状")
        print("=" * 60)
        result = await conn.execute(text("""
            SELECT config_key, config_value, value_type
            FROM system_config
            WHERE config_key LIKE 'RAG_%'
            ORDER BY config_key;
        """))
        rows = result.fetchall()
        if rows:
            for r in rows:
                print(f"  {r.config_key:<32} {r.config_value:<8} ({r.value_type})")
        else:
            print("  (无 RAG_* 配置)")

        result = await conn.execute(text("SELECT COUNT(*) FROM system_config;"))
        print(f"\n  📊 system_config 总行数: {result.scalar_one()}")

        # 检查是否还有遗留旧 key
        keys_list = ",".join(f"'{k}'" for k in OBSOLETE_KEYS)
        result = await conn.execute(text(f"""
            SELECT config_key FROM system_config
            WHERE config_key IN ({keys_list});
        """))
        leftovers = [r.config_key for r in result.fetchall()]
        if leftovers:
            print(f"\n  ⚠️  仍有遗留旧 key: {leftovers}")
        else:
            print(f"\n  ✅ 旧 key 已全部清理")

        print("\n" + "=" * 60)
        print("✅ 完成")
        print("=" * 60)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())