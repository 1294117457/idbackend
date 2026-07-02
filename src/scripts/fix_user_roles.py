"""检查和修复用户角色"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.infra.database import AsyncSessionLocal
from src.models.user import User, Role, UserRole
from sqlalchemy import select, delete


async def check_and_fix_user_roles():
    async with AsyncSessionLocal() as db:
        try:
            print("=" * 50)
            print("用户角色检查与修复")
            print("=" * 50)

            # 列出所有角色
            print("\n[1] 所有可用角色:")
            result = await db.execute(select(Role))
            roles = {r.role_code: r for r in result.scalars().all()}
            for code, role in roles.items():
                print(f"  - {code}: {role.role_name}")

            # 检查 33120202201909 用户
            print("\n[2] 检查 33120202201909 用户:")
            result = await db.execute(select(User).where(User.username == "33120202201909"))
            user = result.scalar_one_or_none()
            
            if not user:
                # 尝试其他用户名格式
                result = await db.execute(select(User).where(User.username.like("%33120202201909%")))
                user = result.scalar_one_or_none()
            
            if user:
                print(f"  用户: {user.username} (id={user.id})")
                
                # 获取当前角色
                result = await db.execute(
                    select(Role.role_code)
                    .join(UserRole, UserRole.role_id == Role.id)
                    .where(UserRole.user_id == user.id)
                )
                current_roles = list(result.scalars().all())
                print(f"  当前角色: {current_roles if current_roles else '无'}")
                
                # 分配 admin 角色
                admin_role = roles.get("admin")
                if admin_role:
                    # 检查是否已有 admin 角色
                    if "admin" not in current_roles:
                        # 删除现有角色绑定
                        await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
                        
                        # 添加 admin 角色
                        user_role = UserRole(user_id=user.id, role_id=admin_role.id)
                        db.add(user_role)
                        await db.commit()
                        print(f"  已分配 admin 角色")
                    else:
                        print(f"  已有 admin 角色")
                else:
                    print(f"  错误: admin 角色不存在")
            else:
                print("  用户不存在!")

            print("\n[完成]")
            
        except Exception as e:
            await db.rollback()
            print(f"[错误] {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(check_and_fix_user_roles())
