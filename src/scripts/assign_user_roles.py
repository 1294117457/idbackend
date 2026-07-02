"""分配用户角色脚本

运行：
    python -m src.scripts.assign_user_roles
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.infra.database import AsyncSessionLocal
from src.models.user import User, Role, UserRole
from sqlalchemy import select


async def assign_roles():
    async with AsyncSessionLocal() as db:
        try:
            print("=" * 50)
            print("用户角色分配")
            print("=" * 50)

            # 清除现有 user_role 记录（可选）
            print("\n[1] 清除现有用户角色绑定...")

            # 获取 abc 用户
            result = await db.execute(select(User).where(User.username == "abc"))
            abc_user = result.scalar_one_or_none()

            # 获取 super_admin 角色
            result = await db.execute(select(Role).where(Role.role_code == "super_admin"))
            super_admin_role = result.scalar_one_or_none()

            if abc_user and super_admin_role:
                # 检查是否已有绑定
                result = await db.execute(
                    select(UserRole).where(
                        UserRole.user_id == abc_user.id,
                        UserRole.role_id == super_admin_role.id
                    )
                )
                existing = result.scalar_one_or_none()
                if not existing:
                    ur = UserRole(user_id=abc_user.id, role_id=super_admin_role.id)
                    db.add(ur)
                    print(f"[绑定] abc -> super_admin")
                else:
                    print(f"[已有] abc 已绑定 super_admin")

            # 获取学生用户
            result = await db.execute(select(User).where(User.username == "33120202201909@stu.xmu.edu.cn"))
            student_user = result.scalar_one_or_none()

            # 获取 admin 角色
            result = await db.execute(select(Role).where(Role.role_code == "admin"))
            admin_role = result.scalar_one_or_none()

            if student_user and admin_role:
                # 检查是否已有绑定
                result = await db.execute(
                    select(UserRole).where(
                        UserRole.user_id == student_user.id,
                        UserRole.role_id == admin_role.id
                    )
                )
                existing = result.scalar_one_or_none()
                if not existing:
                    ur = UserRole(user_id=student_user.id, role_id=admin_role.id)
                    db.add(ur)
                    print(f"[绑定] 33120202201909@stu.xmu.edu.cn -> admin")
                else:
                    print(f"[已有] 学生用户已绑定 admin")

            await db.commit()

            # 验证结果 - 用查询方式而不是 relationship
            print("\n[2] 验证绑定结果...")
            result = await db.execute(
                select(User.username, Role.role_code)
                .join(UserRole, UserRole.user_id == User.id)
                .join(Role, Role.id == UserRole.role_id)
            )
            for username, role_code in result.all():
                print(f"  {username} -> {role_code}")

            print("\n[完成] 角色分配成功！")

        except Exception as e:
            await db.rollback()
            print(f"[错误] {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(assign_roles())
