"""用户服务"""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Dict, Any
from datetime import datetime

from src.models import User, Role, Permission, Application
from src.models.user import UserRole, RolePermission, UserStatus
from src.infra.jwt import hash_password
from src.infra.database import AsyncSessionLocal


class UserService:
    """用户服务"""

    @staticmethod
    async def load_user_auth_info(user_id: int) -> Optional[Dict[str, Any]]:
        """加载用户鉴权所需的数据库信息（状态 + 角色 + 权限），专供 PermissionMiddleware 调用。

        Returns:
            None  → 账号已被禁用，中间件应返回 401
            dict  → 包含 user_id / username / roles / permissions
        """
        async with AsyncSessionLocal() as db:
            user = await db.get(User, user_id)
            if not user:
                return {
                    "user_id": user_id,
                    "username": "",
                    "is_admin": False,
                    "roles": [],
                    "permissions": [],
                }

            if user.status != UserStatus.ACTIVE.value:
                return None  # 账号禁用 → 触发 401

            result = await db.execute(
                select(
                    Role.id, Role.role_code, Role.role_name, Permission.permission_code
                )
                .select_from(UserRole)
                .join(Role, UserRole.role_id == Role.id)
                .join(RolePermission, RolePermission.role_id == Role.id)
                .join(Permission, RolePermission.permission_id == Permission.id)
                .where(UserRole.user_id == user_id)
                .where(Role.status == True)
                .where(Permission.status == True)
            )
            rows = result.all()

            role_map: Dict[int, dict] = {}
            perm_set: set = set()
            for role_id, role_code, role_name, perm_code in rows:
                role_map[role_id] = {"roleCode": role_code, "roleName": role_name}
                perm_set.add(perm_code)

            return {
                "user_id": user.id,
                "username": user.username,
                "is_admin": False,
                "roles": list(role_map.values()),
                "permissions": sorted(perm_set),
            }

    @staticmethod
    async def get_user_by_id(
        db: AsyncSession,
        user_id: int,
    ) -> Optional[User]:
        """根据ID获取用户"""
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_by_username(
        db: AsyncSession,
        username: str,
    ) -> Optional[User]:
        """根据用户名获取用户"""
        result = await db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    @staticmethod
    async def update_user(
        db: AsyncSession,
        user_id: int,
        **kwargs,
    ) -> Optional[User]:
        """更新用户信息"""
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return None

        for key, value in kwargs.items():
            if hasattr(user, key) and value is not None:
                setattr(user, key, value)

        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def bind_student_info(
        db: AsyncSession,
        user_id: int,
        student_id: str,
        full_name: str,
        major: str,
        grade: int,
        enrollment_year: int,
    ) -> Optional[User]:
        """绑定学生信息"""
        return await UserService.update_user(
            db,
            user_id,
            student_id=student_id,
            full_name=full_name,
            major=major,
            grade=grade,
            enrollment_year=enrollment_year,
        )

    @staticmethod
    async def confirm_student(
        db: AsyncSession,
        user_id: int,
    ) -> Optional[User]:
        """确认学生身份"""
        return await UserService.update_user(
            db,
            user_id,
            is_confirmed=True,
        )

    @staticmethod
    async def get_user_scores(
        db: AsyncSession,
        user_id: int,
    ) -> dict:
        """获取用户积分"""
        user = await UserService.get_user_by_id(db, user_id)
        if not user:
            return {"academic": 0, "specialty": 0, "comprehensive": 0}

        return {
            "academic": user.academic_score or 0,
            "specialty": user.specialty_score or 0,
            "comprehensive": user.comprehensive_score or 0,
            "total": (user.academic_score or 0)
            + (user.specialty_score or 0)
            + (user.comprehensive_score or 0),
        }

    @staticmethod
    async def update_user_scores(
        db: AsyncSession,
        user_id: int,
        academic: Optional[float] = None,
        specialty: Optional[float] = None,
        comprehensive: Optional[float] = None,
    ) -> Optional[User]:
        """更新用户积分"""
        updates = {}
        if academic is not None:
            updates["academic_score"] = academic
        if specialty is not None:
            updates["specialty_score"] = specialty
        if comprehensive is not None:
            updates["comprehensive_score"] = comprehensive

        if updates:
            return await UserService.update_user(db, user_id, **updates)
        return await UserService.get_user_by_id(db, user_id)

    @staticmethod
    async def list_users(
        db: AsyncSession,
        role: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[List[User], int]:
        """获取用户列表"""
        query = select(User)

        # 获取总数
        from sqlalchemy import func

        count_result = await db.execute(select(func.count()).select_from(User))
        total = count_result.scalar()

        # 分页
        query = query.offset((page - 1) * size).limit(size)
        result = await db.execute(query)
        users = result.scalars().all()

        return list(users), total

    @staticmethod
    async def create_user(
        db: AsyncSession,
        username: str,
        password: str,
    ) -> User:
        """创建用户"""
        user = User(
            username=username,
            password=hash_password(password),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def delete_user(
        db: AsyncSession,
        user_id: int,
    ) -> bool:
        """删除用户"""
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return False

        await db.delete(user)
        await db.commit()
        return True
