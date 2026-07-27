"""system_config 表结构同步脚本

同步 system_config 表为 ORM 模型所需结构，不迁移任何数据。

目标表结构：
  config_key:    主键（varchar 100），不再有独立 unique 约束
  config_value:  varchar 500 NOT NULL
  description:   varchar 200
  category:      varchar 50 NOT NULL DEFAULT 'OTHER'
  value_type:    varchar 20 NOT NULL DEFAULT 'string'
  is_sensitive:  boolean NOT NULL DEFAULT FALSE
  created_at / updated_at: timestamp with time zone（TimestampMixin）

用法（服务器上）：
  cd /home/dustp/codes/idproject/idbackend
  python3 scripts/migrate_system_config_schema.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from src.infra.config import get_async_database_url


# 目标列定义：(列名, 类型)
TARGET_COLUMNS = [
    "config_key",
    "config_value",
    "description",
    "category",
    "value_type",
    "is_sensitive",
    "created_at",
    "updated_at",
]


async def main():
    url = get_async_database_url()
    print(f"🔗 连接: {url}\n")

    engine = create_async_engine(url, echo=False)

    async with engine.begin() as conn:
        # ── 前置检查 ────────────────────────────────────────────────
        print("=" * 60)
        print("🔍 前置检查")
        print("=" * 60)

        # 现有列
        result = await conn.execute(text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'system_config' AND table_schema = 'public'
            ORDER BY ordinal_position;
        """))
        cols = {r.column_name: (r.data_type, r.is_nullable, r.column_default) for r in result.fetchall()}

        # 现有主键列
        result = await conn.execute(text("""
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_name = 'system_config'
              AND tc.table_schema = 'public'
              AND tc.constraint_type = 'PRIMARY KEY';
        """))
        pk_columns = [r.column_name for r in result.fetchall()]

        # 行数
        result = await conn.execute(text("SELECT COUNT(*) FROM system_config;"))
        count = result.scalar_one()

        print(f"  现有列：{list(cols.keys())}")
        print(f"  主键列：{pk_columns}")
        print(f"  行数：{count}\n")

        for col_name, (dtype, nullable, default) in cols.items():
            flags = f"default={default}" if default else ""
            flags += " NULL" if nullable == 'YES' else " NOT NULL"
            print(f"    {col_name:<15} {dtype:<28} {flags}")

        # ── 检查是否已是目标结构 ───────────────────────────────────
        target_cols = {'category', 'value_type', 'is_sensitive'}
        missing = target_cols - set(cols.keys())
        has_config_key_pk = 'config_key' in pk_columns

        if not missing and has_config_key_pk:
            print("\n  ✅ system_config 已为目标结构，跳过")
            print("=" * 60)
            await engine.dispose()
            return

        # ── 同步列 ─────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("📦 同步表结构")
        print("=" * 60)

        alter_cmds = [
            ("category",     "ALTER TABLE system_config ADD COLUMN IF NOT EXISTS category VARCHAR(50) NOT NULL DEFAULT 'OTHER';"),
            ("value_type",   "ALTER TABLE system_config ADD COLUMN IF NOT EXISTS value_type VARCHAR(20) NOT NULL DEFAULT 'string';"),
            ("is_sensitive", "ALTER TABLE system_config ADD COLUMN IF NOT EXISTS is_sensitive BOOLEAN NOT NULL DEFAULT FALSE;"),
        ]

        for col_name, sql in alter_cmds:
            if col_name in cols:
                print(f"  ⏭️  列已存在，跳过: {col_name}")
                continue
            try:
                await conn.execute(text(sql))
                print(f"  ✅ 添加列: {col_name}")
            except Exception as e:
                # IF NOT EXISTS 可能报 duplicate 错误但无害
                err_s = str(e).lower()
                if "already exists" in err_s or "duplicate" in err_s:
                    print(f"  ⏭️  列已存在（并发）: {col_name}")
                else:
                    print(f"  ⚠️  添加列 {col_name} 失败: {e}")

        # ── 处理约束 ───────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("🔧 处理约束")
        print("=" * 60)

        # 重新查询 PK（迁移后可能已变）
        result = await conn.execute(text("""
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_name = 'system_config'
              AND tc.table_schema = 'public'
              AND tc.constraint_type = 'PRIMARY KEY';
        """))
        pk_columns = {r.column_name for r in result.fetchall()}

        # 已有 id 主键（非 config_key）→ 不可再添主键，跳过
        if pk_columns and 'config_key' not in pk_columns:
            print(f"  ⚠️  表已有主键列 {pk_columns}（非 config_key），不再修改主键。")
            print(f"     若需将 config_key 设为主键，请先手动处理 id 列。")
        else:
            # 删除 config_key 上多余的 UNIQUE 约束
            try:
                async with conn.begin_nested():
                    await conn.execute(text("""
                        DO $$
                        DECLARE
                            cons_name TEXT;
                        BEGIN
                            FOR cons_name IN
                                SELECT tc.constraint_name
                                FROM information_schema.table_constraints tc
                                JOIN information_schema.key_column_usage kcu
                                  ON tc.constraint_name = kcu.constraint_name
                                WHERE tc.table_name = 'system_config'
                                  AND tc.constraint_schema = 'public'
                                  AND tc.constraint_type = 'UNIQUE'
                                  AND kcu.column_name = 'config_key'
                            LOOP
                                EXECUTE 'ALTER TABLE system_config DROP CONSTRAINT ' || cons_name;
                                RAISE NOTICE '已删除 UNIQUE 约束: %', cons_name;
                            END LOOP;
                        END $$;
                    """))
                print("  ✅ config_key UNIQUE 约束已清理")
            except Exception as e:
                print(f"  ⚠️  UNIQUE 约束清理: {e}")

            # 确保 config_key 为主键
            if 'config_key' in pk_columns:
                print("  ✅ config_key 已为主键")
            else:
                try:
                    async with conn.begin_nested():
                        await conn.execute(text("""
                            DO $$
                            BEGIN
                                IF NOT EXISTS (
                                    SELECT 1
                                    FROM information_schema.table_constraints tc
                                    JOIN information_schema.key_column_usage kcu
                                      ON tc.constraint_name = kcu.constraint_name
                                    WHERE tc.table_name = 'system_config'
                                      AND tc.constraint_type = 'PRIMARY KEY'
                                      AND tc.table_schema = 'public'
                                      AND kcu.column_name = 'config_key'
                                ) THEN
                                    ALTER TABLE system_config ADD PRIMARY KEY (config_key);
                                    RAISE NOTICE '已添加 config_key 主键';
                                ELSE
                                    RAISE NOTICE 'config_key 主键已存在';
                                END IF;
                            END $$;
                        """))
                    print("  ✅ config_key 主键已就绪")
                except DBAPIError as e:
                    err_s = str(e).lower()
                    if "multiple primary keys" in err_s or "already exists" in err_s:
                        print(f"  ⚠️  主键冲突（表已有其他主键）: {e}")
                    else:
                        print(f"  ⚠️  主键处理异常: {e}")

        # ── 验证 ────────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("📋 验证结果")
        print("=" * 60)

        result = await conn.execute(text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'system_config' AND table_schema = 'public'
            ORDER BY ordinal_position;
        """))
        rows = list(result.fetchall())

        print(f"\n  system_config 列结构（共 {len(rows)} 列）：")
        for r in rows:
            flags = []
            if r.column_default:
                flags.append(f"default={r.column_default}")
            flags_s = f"  [{', '.join(flags)}]" if flags else ""
            nullable = "NULL" if r.is_nullable == 'YES' else "NOT NULL"
            print(f"    {r.column_name:<15} {r.data_type:<28} {nullable:<10}{flags_s}")

        result = await conn.execute(text("SELECT COUNT(*) FROM system_config;"))
        print(f"\n  📊 行数：{result.scalar_one()}")

        result = await conn.execute(text("""
            SELECT tc.constraint_name, tc.constraint_type, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_name = 'system_config'
              AND tc.table_schema = 'public'
            ORDER BY tc.constraint_type, kcu.column_name;
        """))
        print(f"\n  📇 约束：")
        constraints = list(result.fetchall())
        if constraints:
            for r in constraints:
                print(f"    {r.constraint_name:<30} {r.constraint_type:<15} ({r.column_name})")
        else:
            print("    (无)")

        print("\n" + "=" * 60)
        print("✅ 完成")
        print("=" * 60)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
