"""Role 数据访问层

职责：只做"读 / 写 ORM"，没有业务规则。
"""
from typing import List, Optional, Dict, Any

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import Role, UserRole, RolePermission, Permission, User


class RoleRepository:
    """role 表的数据访问层"""

    # =========================================================================
    # 基础查询
    # =========================================================================

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        role_id: int,
    ) -> Optional[Role]:
        """根据 ID 查询角色"""
        return await db.get(Role, role_id)

    @staticmethod
    async def get_by_code(
        db: AsyncSession,
        role_code: str,
    ) -> Optional[Role]:
        """根据角色编码查询角色"""
        result = await db.execute(
            select(Role).where(Role.role_code == role_code)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(
        db: AsyncSession,
        status: Optional[bool] = None,
    ) -> List[Role]:
        """获取所有角色"""
        query = select(Role)
        if status is not None:
            query = query.where(Role.status == status)
        query = query.order_by(Role.sort_order.asc())
        result = await db.execute(query)
        return list(result.scalars().all())

    # =========================================================================
    # 写操作
    # =========================================================================

    @staticmethod
    async def insert(
        db: AsyncSession,
        role: Role,
    ) -> Role:
        """新增角色"""
        db.add(role)
        await db.flush()
        return role

    @staticmethod
    async def update(
        db: AsyncSession,
        role: Role,
    ) -> Role:
        """更新角色"""
        await db.flush()
        return role

    @staticmethod
    async def delete_by_id(
        db: AsyncSession,
        role_id: int,
    ) -> bool:
        """删除角色（级联删除关联）"""
        role = await db.get(Role, role_id)
        if not role:
            return False

        # 删除角色权限关联
        await db.execute(
            delete(RolePermission).where(RolePermission.role_id == role_id)
        )
        # 删除用户角色关联
        await db.execute(
            delete(UserRole).where(UserRole.role_id == role_id)
        )
        # 删除角色
        await db.delete(role)
        await db.flush()
        return True

    # =========================================================================
    # 角色权限关联
    # =========================================================================

    @staticmethod
    async def get_role_permission_ids(
        db: AsyncSession,
        role_id: int,
    ) -> List[int]:
        """获取角色的权限 ID 列表"""
        result = await db.execute(
            select(RolePermission.permission_id).where(RolePermission.role_id == role_id)
        )
        return [row[0] for row in result.all()]

    @staticmethod
    async def get_role_permissions(
        db: AsyncSession,
        role_id: int,
    ) -> List[Permission]:
        """获取角色的所有权限"""
        result = await db.execute(
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
            .where(Permission.status == True)
        )
        return list(result.scalars().all())

    @staticmethod
    async def assign_permissions(
        db: AsyncSession,
        role_id: int,
        permission_ids: List[int],
    ) -> None:
        """分配角色权限（先删后加）"""
        # 删除现有权限关联
        await db.execute(
            delete(RolePermission).where(RolePermission.role_id == role_id)
        )
        # 添加新权限关联
        for permission_id in permission_ids:
            db.add(RolePermission(role_id=role_id, permission_id=permission_id))
        await db.flush()

    # =========================================================================
    # 用户角色关联
    # =========================================================================

    @staticmethod
    async def get_user_roles(
        db: AsyncSession,
        user_id: int,
    ) -> List[Role]:
        """获取用户的所有角色"""
        result = await db.execute(
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .where(Role.status == True)
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_user_role_codes_by_user_ids(
        db: AsyncSession,
        user_ids: List[int],
    ) -> Dict[int, List[str]]:
        """批量查询：给定 user_id 列表，返回 {user_id: [role_code, ...]} 映射

        替代 N+1：用一次 IN 查询替代逐个 user 一次查询。
        注意：Role.status == True 过滤条件保持与 get_user_roles 一致。
        """
        if not user_ids:
            return {}
        result = await db.execute(
            select(UserRole.user_id, Role.role_code)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id.in_(user_ids))
            .where(Role.status == True)
        )
        role_map: Dict[int, List[str]] = {uid: [] for uid in user_ids}
        for uid, code in result.all():
            if uid in role_map and code:
                role_map[uid].append(code)
        return role_map

    @staticmethod
    async def get_user_role_ids(
        db: AsyncSession,
        user_id: int,
    ) -> List[int]:
        """获取用户角色 ID 列表"""
        result = await db.execute(
            select(UserRole.role_id).where(UserRole.user_id == user_id)
        )
        return [row[0] for row in result.all()]

    @staticmethod
    async def assign_roles_to_user(
        db: AsyncSession,
        user_id: int,
        role_ids: List[int],
    ) -> None:
        """分配用户角色（先删后加）"""
        # 删除现有角色关联
        await db.execute(
            delete(UserRole).where(UserRole.user_id == user_id)
        )
        # 添加新角色关联
        for role_id in role_ids:
            db.add(UserRole(user_id=user_id, role_id=role_id))
        await db.flush()

    # =========================================================================
    # 缓存清理（关联查询）
    # =========================================================================

    @staticmethod
    async def get_users_by_role(
        db: AsyncSession,
        role_id: int,
    ) -> List[User]:
        """获取拥有某角色的所有用户"""
        result = await db.execute(
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .where(UserRole.role_id == role_id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_role_user_ids(
        db: AsyncSession,
        role_id: int,
    ) -> List[int]:
        """获取拥有某角色的所有用户 ID"""
        result = await db.execute(
            select(UserRole.user_id).where(UserRole.role_id == role_id)
        )
        return [row[0] for row in result.all()]


__all__ = ["RoleRepository"]
