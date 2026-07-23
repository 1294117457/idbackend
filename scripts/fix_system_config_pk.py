"""修复 system_config 表主键结构

目标：
  - 移除 id 列（SERIAL 主键）
  - 将 config_key 设为唯一主键

执行前请确认：
  1. config_key 列无重复值（UNIQUE 约束已存在，数据应唯一）
  2. 无其他外键引用 id 列

用法（服务器上）：
  cd /home/dustp/codes/idproject/idbackend
  python3 scripts/fix_system_config_pk.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from src.infra.config import get_async_database_url


async def main():
    url = get_async_database_url()
    print(f"🔗 连接: {url}\n")

    engine = create_async_engine(url, echo=False)

    async with engine.begin() as conn:
        # ── 前置检查 ────────────────────────────────────────────────
        print("=" * 60)
        print("🔍 前置检查")
        print("=" * 60)

        # 列信息
        result = await conn.execute(text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'system_config' AND table_schema = 'public'
            ORDER BY ordinal_position;
        """))
        cols = {r.column_name: (r.data_type, r.is_nullable, r.column_default) for r in result.fetchall()}

        # 约束信息
        result = await conn.execute(text("""
            SELECT tc.constraint_name, tc.constraint_type, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_name = 'system_config'
              AND tc.table_schema = 'public'
            ORDER BY tc.constraint_type;
        """))
        constraints = list(result.fetchall())

        result = await conn.execute(text("SELECT COUNT(*) FROM system_config;"))
        count = result.scalar_one()

        print(f"\n  当前列：{list(cols.keys())}")
        print(f"  当前约束：")
        for r in constraints:
            print(f"    {r.constraint_name:<30} {r.constraint_type:<15} ({r.column_name})")
        print(f"\n  行数：{count}")

        # 检查是否有 id 列
        has_id = "id" in cols
        print(f"\n  有 id 列：{has_id}")

        if has_id:
            # 检查 id 是否有重复（引用关系问题）
            result = await conn.execute(text("""
                SELECT id, COUNT(*) as cnt
                FROM system_config
                GROUP BY id
                HAVING COUNT(*) > 1;
            """))
            dup_ids = list(result.fetchall())
            if dup_ids:
                print(f"\n  ⚠️  警告：id 列存在重复值 {dup_ids}")
            else:
                print(f"  ✅ id 列无重复值，可安全移除")

        # 检查 config_key 唯一性
        result = await conn.execute(text("""
            SELECT config_key, COUNT(*) as cnt
            FROM system_config
            GROUP BY config_key
            HAVING COUNT(*) > 1;
        """))
        dup_keys = list(result.fetchall())
        if dup_keys:
            print(f"\n  ❌ config_key 存在重复值：")
            for r in dup_keys:
                print(f"    config_key='{r.config_key}' ({r.cnt} 次)")
            print("\n  请先清理重复数据后再运行本脚本！")
            print("=" * 60)
            await engine.dispose()
            return
        else:
            print(f"  ✅ config_key 值唯一")

        # 检查是否已是 config_key 主键
        pk_cols = [r.column_name for r in constraints if r.constraint_type == "PRIMARY KEY"]
        if pk_cols == ["config_key"] and not has_id:
            print("\n  ✅ 表结构已正确（config_key 为主键，无 id 列），跳过")
            print("=" * 60)
            await engine.dispose()
            return

        # ── 执行修复 ────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("🔧 执行修复")
        print("=" * 60)

        # 1. 删除 config_key 上的 UNIQUE 约束（之后会变为主键）
        unique_cons = [r.constraint_name for r in constraints
                       if r.constraint_type == "UNIQUE" and r.column_name == "config_key"]
        for cons_name in unique_cons:
            try:
                await conn.execute(text(f'ALTER TABLE system_config DROP CONSTRAINT "{cons_name}";'))
                print(f"  ✅ 删除 UNIQUE 约束: {cons_name}")
            except Exception as e:
                print(f"  ⚠️  删除 UNIQUE 约束 {cons_name} 失败: {e}")

        # 2. 删除 id 列（必须是 NOT NULL 才能设主键）
        if has_id:
            id_nullable = cols["id"][1]
            id_is_pk = "id" in pk_cols

            if id_is_pk and id_nullable == "NO":
                # 先移除 id 主键约束（改为普通列），再删列
                try:
                    # 先查主键约束名
                    result = await conn.execute(text("""
                        SELECT constraint_name
                        FROM information_schema.table_constraints
                        WHERE table_name = 'system_config'
                          AND table_schema = 'public'
                          AND constraint_type = 'PRIMARY KEY'
                          AND table_name = 'system_config';
                    """))
                    pk_cons = [r.constraint_name for r in result.fetchall() if r.constraint_name]
                    for cons_name in pk_cons:
                        await conn.execute(text(f'ALTER TABLE system_config DROP CONSTRAINT "{cons_name}";'))
                        print(f"  ✅ 删除主键约束: {cons_name}")
                except Exception as e:
                    print(f"  ⚠️  删除主键约束失败: {e}")

            # 删除 id 列
            try:
                await conn.execute(text("ALTER TABLE system_config DROP COLUMN id;"))
                print(f"  ✅ 删除 id 列")
            except Exception as e:
                print(f"  ⚠️  删除 id 列失败: {e}")

        # 3. 将 config_key 设为主键
        try:
            await conn.execute(text("ALTER TABLE system_config ADD PRIMARY KEY (config_key);"))
            print(f"  ✅ config_key 设为主键")
        except DBAPIError as e:
            err_s = str(e).lower()
            if "already exists" in err_s or "duplicate" in err_s:
                print(f"  ⏭️  config_key 主键已存在，跳过")
            else:
                print(f"  ❌ 设置主键失败: {e}")

        # ── 验证 ────────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("📋 验证结果")
        print("=" * 60)

        # 重新查询
        result = await conn.execute(text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'system_config' AND table_schema = 'public'
            ORDER BY ordinal_position;
        """))
        cols_after = list(result.fetchall())

        result = await conn.execute(text("""
            SELECT tc.constraint_name, tc.constraint_type, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_name = 'system_config'
              AND tc.table_schema = 'public'
            ORDER BY tc.constraint_type;
        """))
        constraints_after = list(result.fetchall())

        print(f"\n  system_config 列结构（共 {len(cols_after)} 列）：")
        for r in cols_after:
            nullable = "NULL" if r.is_nullable == 'YES' else "NOT NULL"
            default = f"  default={r.column_default}" if r.column_default else ""
            print(f"    {r.column_name:<15} {r.data_type:<28} {nullable}{default}")

        print(f"\n  约束：")
        for r in constraints_after:
            print(f"    {r.constraint_name:<30} {r.constraint_type:<15} ({r.column_name})")

        pk_cols_after = [r.column_name for r in constraints_after if r.constraint_type == "PRIMARY KEY"]
        print(f"\n  主键：{pk_cols_after}")
        if pk_cols_after == ["config_key"]:
            print("  ✅ 主键结构正确！")
        else:
            print(f"  ⚠️  主键结构异常，期望 ['config_key']，实际 {pk_cols_after}")

        print("\n" + "=" * 60)
        print("✅ 完成")
        print("=" * 60)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
