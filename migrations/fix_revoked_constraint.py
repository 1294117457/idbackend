"""修复 REVOKED 状态约束

将 ck_application_status 约束更新为包含 REVOKED 状态。
"""
import asyncio
import os
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv()


async def main():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("错误: 未设置 DATABASE_URL")
        return

    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = create_async_engine(database_url, echo=False)

    async with engine.begin() as conn:
        # 1. 检查现有数据中的状态值
        result = await conn.execute(text("SELECT DISTINCT status FROM applications"))
        existing_statuses = [row[0] for row in result.fetchall()]
        print(f"现有状态值: {existing_statuses}")

        # 2. 定义允许的状态列表（包含现有数据中的所有状态）
        allowed_statuses = {'DRAFT', 'APPLYING', 'PASSED', 'REJECTED', 'CANCELLED', 'REVOKED', 'WITHDRAWN', 'DISCARDED'}

        # 3. 检查是否有不在允许列表中的状态值
        disallowed = [s for s in existing_statuses if s not in allowed_statuses]
        if disallowed:
            print(f"发现未处理的状态值: {disallowed}")
            return

        # 4. 删除旧约束
        await conn.execute(text(
            "ALTER TABLE applications DROP CONSTRAINT IF EXISTS ck_application_status"
        ))
        print("已删除旧约束")

        # 5. 添加新约束（包含所有现有状态 + REVOKED）
        await conn.execute(text("""
            ALTER TABLE applications ADD CONSTRAINT ck_application_status CHECK (
                status IN ('DRAFT', 'APPLYING', 'PASSED', 'REJECTED', 'CANCELLED', 'REVOKED', 'WITHDRAWN', 'DISCARDED')
            )
        """))
        print("已添加新约束 (含 REVOKED)")

    await engine.dispose()
    print("约束修复成功!")


if __name__ == "__main__":
    asyncio.run(main())
