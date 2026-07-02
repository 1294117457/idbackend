"""RBAC 核心服务

实现基于角色的访问控制（Role-Based Access Control），包括：
- 用户角色和权限的获取（含缓存）
- 角色管理（CRUD）
- 权限管理（CRUD）
- 用户角色分配
- 角色权限分配

特性：
- SuperAdmin 白名单机制：通过 SYSTEM_ACCOUNTS 配置的用户自动获得全部权限
- Redis 缓存：用户角色和权限信息缓存 30 分钟
"""
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_
from sqlalchemy.orm import selectinload
import json

from src.models.user import User, Role, Permission, UserRole, RolePermission
from src.infra.redis import get_redis
from src.infra.config import get_settings

settings = get_settings()


class RbacService:
    """RBAC 核心服务（含 SuperAdmin 白名单）"""

    CACHE_TTL = 30  # 缓存过期时间(分钟)
    USER_ROLES_KEY = "rbac:user:roles:"
    USER_PERMS_KEY = "rbac:user:perms:"

    # ========== 缓存键 ==========

    @classmethod
    def _get_admin_users(cls) -> List[str]:
        """获取管理员白名单"""
        return settings.SYSTEM_ACCOUNTS

    @classmethod
    def _is_admin(cls, username: str) -> bool:
        """检查用户名是否在白名单中（仅用于系统初始用户）"""
        return username in cls._get_admin_users()

    @classmethod
    async def _is_admin_by_user_id(cls, db: AsyncSession, user_id: int) -> bool:
        """通过用户ID检查是否为管理员（基于RBAC）"""
        user_roles = await cls.get_user_roles(db, user_id)
        return "admin" in user_roles

    # ==================== 权限校验方法 ====================

    @staticmethod
    async def get_user_roles(db: AsyncSession, user_id: int) -> List[str]:
        """获取用户角色列表（含缓存）

        Args:
            db: 数据库会话
            user_id: 用户ID

        Returns:
            角色代码列表，如 ["admin", "user"]
        """
        redis = await get_redis()
        cache_key = f"{RbacService.USER_ROLES_KEY}{user_id}"

        # 查缓存
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)

        # 查数据库
        result = await db.execute(
            select(Role.role_code)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id)
        )
        roles = list(result.scalars().all())

        # 写缓存
        await redis.setex(cache_key, RbacService.CACHE_TTL * 60, json.dumps(roles))
        return roles

    @staticmethod
    async def get_user_permissions(db: AsyncSession, user_id: int) -> List[str]:
        """获取用户权限列表（含缓存，含 SuperAdmin 自动扩展）

        Args:
            db: 数据库会话
            user_id: 用户ID

        Returns:
            权限代码列表，如果是管理员则返回 ["*"] 表示全部权限
        """
        # 1. 查询用户
        user = await db.get(User, user_id)
        if not user:
            return []

        # 2. 【关键】检查是否在白名单中
        if RbacService._is_admin(user.username):
            return ["*"]  # 管理员拥有所有权限

        # 3. 普通用户走标准 RBAC
        redis = await get_redis()
        cache_key = f"{RbacService.USER_PERMS_KEY}{user_id}"

        # 查缓存
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)

        # 查数据库
        result = await db.execute(
            select(Permission.code)
            .join(RolePermission, Permission.id == RolePermission.permission_id)
            .join(UserRole, RolePermission.role_id == UserRole.role_id)
            .where(UserRole.user_id == user_id)
            .where(Permission.status == True)
        )
        perms = list(set(result.scalars().all()))  # 去重

        # 写缓存
        await redis.setex(cache_key, RbacService.CACHE_TTL * 60, json.dumps(perms))
        return perms

    @staticmethod
    async def has_permission(db: AsyncSession, user_id: int, code: str) -> bool:
        """检查用户是否拥有指定权限

        Args:
            db: 数据库会话
            user_id: 用户ID
            code: 权限代码

        Returns:
            是否拥有该权限
        """
        perms = await RbacService.get_user_permissions(db, user_id)
        return "*" in perms or code in perms

    @staticmethod
    async def has_any_role(db: AsyncSession, user_id: int, *required_roles: str) -> bool:
        """检查用户是否拥有指定角色（任意一个即可）

        Args:
            db: 数据库会话
            user_id: 用户ID
            required_roles: 必需的角色列表

        Returns:
            是否拥有其中任意一个角色
        """
        user_roles = await RbacService.get_user_roles(db, user_id)
        return any(role in user_roles for role in required_roles)

    @staticmethod
    async def is_admin(db: AsyncSession, user_id: int) -> bool:
        """判断是否是管理员用户（检查 admin 角色或白名单）

        Args:
            db: 数据库会话
            user_id: 用户ID

        Returns:
            是否是管理员
        """
        user = await db.get(User, user_id)
        if not user:
            return False

        # 优先检查白名单用户
        if RbacService._is_admin(user.username):
            return True

        # 检查用户是否拥有 admin 角色
        user_roles = await RbacService.get_user_roles(db, user_id)
        return "admin" in user_roles

    @staticmethod
    async def clear_user_cache(user_id: int):
        """清除用户缓存

        Args:
            user_id: 用户ID
        """
        redis = await get_redis()
        await redis.delete(f"{RbacService.USER_ROLES_KEY}{user_id}")
        await redis.delete(f"{RbacService.USER_PERMS_KEY}{user_id}")

    # ==================== 角色管理 ====================

    @staticmethod
    async def get_all_roles(db: AsyncSession) -> List[Role]:
        """获取所有角色

        Args:
            db: 数据库会话

        Returns:
            角色列表
        """
        result = await db.execute(
            select(Role).order_by(Role.sort_order, Role.id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_role_by_id(db: AsyncSession, role_id: int) -> Optional[Role]:
        """根据ID获取角色

        Args:
            db: 数据库会话
            role_id: 角色ID

        Returns:
            角色对象，不存在则返回 None
        """
        return await db.get(Role, role_id)

    @staticmethod
    async def get_role_by_code(db: AsyncSession, role_code: str) -> Optional[Role]:
        """根据代码获取角色

        Args:
            db: 数据库会话
            role_code: 角色代码

        Returns:
            角色对象，不存在则返回 None
        """
        result = await db.execute(
            select(Role).where(Role.role_code == role_code)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_role(
        db: AsyncSession,
        role_code: str,
        role_name: str,
        description: Optional[str] = None,
        sort_order: int = 0,
        is_system: bool = False,
    ) -> Role:
        # 检查是否已存在
        existing = await RbacService.get_role_by_code(db, role_code)
        if existing:
            raise ValueError(f"角色代码已存在: {role_code}")

        role = Role(
            role_code=role_code,
            role_name=role_name,
            description=description,
            sort_order=sort_order,
            status=True,
            is_system=is_system,
        )
        db.add(role)
        await db.commit()
        await db.refresh(role)
        return role

    @staticmethod
    async def update_role(
        db: AsyncSession,
        role_id: int,
        role_code: Optional[str] = None,
        role_name: Optional[str] = None,
        description: Optional[str] = None,
        sort_order: Optional[int] = None,
        status: Optional[bool] = None,
    ) -> Optional[Role]:
        """更新角色

        Args:
            db: 数据库会话
            role_id: 角色ID
            role_code: 角色代码（可选）
            role_name: 角色名称（可选）
            description: 描述（可选）
            sort_order: 排序（可选）
            status: 状态（可选）

        Returns:
            更新后的角色，不存在则返回 None
        """
        role = await db.get(Role, role_id)
        if not role:
            return None

        if role_code is not None:
            role.role_code = role_code
        if role_name is not None:
            role.role_name = role_name
        if description is not None:
            role.description = description
        if sort_order is not None:
            role.sort_order = sort_order
        if status is not None:
            role.status = status

        await db.commit()
        await db.refresh(role)

        # 清除相关用户缓存
        await RbacService._clear_role_users_cache(db, role_id)

        return role

    @staticmethod
    async def delete_role(db: AsyncSession, role_id: int) -> bool:
        """删除角色

        Args:
            db: 数据库会话
            role_id: 角色ID

        Returns:
            是否删除成功
        """
        role = await db.get(Role, role_id)
        if not role:
            return False

        # 系统角色不可删除
        if role.is_system:
            raise ValueError("系统角色不可删除")

        # 清除相关用户缓存
        await RbacService._clear_role_users_cache(db, role_id)

        # 删除用户角色关联
        await db.execute(
            delete(UserRole).where(UserRole.role_id == role_id)
        )

        # 删除角色权限关联
        await db.execute(
            delete(RolePermission).where(RolePermission.role_id == role_id)
        )

        # 删除角色
        await db.delete(role)
        await db.commit()

        return True

    # ==================== 权限管理 ====================

    @staticmethod
    async def get_all_permissions(db: AsyncSession) -> List[Permission]:
        """获取所有权限

        Args:
            db: 数据库会话

        Returns:
            权限列表
        """
        result = await db.execute(
            select(Permission).order_by(Permission.sort_order, Permission.id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_permission_by_id(db: AsyncSession, permission_id: int) -> Optional[Permission]:
        """根据ID获取权限

        Args:
            db: 数据库会话
            permission_id: 权限ID

        Returns:
            权限对象，不存在则返回 None
        """
        return await db.get(Permission, permission_id)

    @staticmethod
    async def get_permission_by_code(db: AsyncSession, code: str) -> Optional[Permission]:
        """根据代码获取权限

        Args:
            db: 数据库会话
            code: 权限代码

        Returns:
            权限对象，不存在则返回 None
        """
        result = await db.execute(
            select(Permission).where(Permission.code == code)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_permission(
        db: AsyncSession,
        code: str,
        name: str,
        route_path: Optional[str] = None,
        description: Optional[str] = None,
        sort_order: int = 0,
    ) -> Permission:
        """创建权限

        Args:
            db: 数据库会话
            code: 权限代码（唯一）
            name: 权限名称
            route_path: 对应后端接口路径
            description: 描述
            sort_order: 排序

        Returns:
            创建的权限
        """
        existing = await RbacService.get_permission_by_code(db, code)
        if existing:
            raise ValueError(f"权限代码已存在: {code}")

        permission = Permission(
            code=code,
            name=name,
            route_path=route_path,
            description=description,
            sort_order=sort_order,
            status=True,
        )
        db.add(permission)
        await db.commit()
        await db.refresh(permission)

        # 重载中间件权限映射
        await RbacService._reload_permission_map()

        return permission

    @staticmethod
    async def update_permission(
        db: AsyncSession,
        permission_id: int,
        name: Optional[str] = None,
        route_path: Optional[str] = None,
        description: Optional[str] = None,
        sort_order: Optional[int] = None,
        status: Optional[bool] = None,
    ) -> Optional[Permission]:
        """更新权限

        Args:
            db: 数据库会话
            permission_id: 权限ID
            name: 权限名称（可选）
            route_path: 对应接口路径（可选）
            description: 描述（可选）
            sort_order: 排序（可选）
            status: 状态（可选）

        Returns:
            更新后的权限，不存在则返回 None
        """
        permission = await db.get(Permission, permission_id)
        if not permission:
            return None

        if name is not None:
            permission.name = name
        if route_path is not None:
            permission.route_path = route_path
        if description is not None:
            permission.description = description
        if sort_order is not None:
            permission.sort_order = sort_order
        if status is not None:
            permission.status = status

        await db.commit()
        await db.refresh(permission)

        # 清除相关用户缓存
        await RbacService._clear_permission_users_cache(db, permission_id)

        # 重载中间件权限映射
        await RbacService._reload_permission_map()

        return permission

    @staticmethod
    async def delete_permission(db: AsyncSession, permission_id: int) -> bool:
        """删除权限

        Args:
            db: 数据库会话
            permission_id: 权限ID

        Returns:
            是否删除成功
        """
        permission = await db.get(Permission, permission_id)
        if not permission:
            return False

        # 清除相关用户缓存
        await RbacService._clear_permission_users_cache(db, permission_id)

        # 删除角色权限关联
        await db.execute(
            delete(RolePermission).where(RolePermission.permission_id == permission_id)
        )

        # 删除权限
        await db.delete(permission)
        await db.commit()

        # 重载中间件权限映射
        await RbacService._reload_permission_map()

        return True

    # ==================== 角色权限分配 ====================

    @staticmethod
    async def get_role_permissions(db: AsyncSession, role_id: int) -> List[Permission]:
        """获取角色的权限列表

        Args:
            db: 数据库会话
            role_id: 角色ID

        Returns:
            权限列表
        """
        result = await db.execute(
            select(Permission)
            .join(RolePermission, Permission.id == RolePermission.permission_id)
            .where(RolePermission.role_id == role_id)
            .where(Permission.status == True)
        )
        return list(result.scalars().all())

    @staticmethod
    async def assign_permissions_to_role(
        db: AsyncSession, role_id: int, permission_ids: List[int]
    ) -> bool:
        """为角色分配权限

        Args:
            db: 数据库会话
            role_id: 角色ID
            permission_ids: 权限ID列表

        Returns:
            是否分配成功
        """
        role = await db.get(Role, role_id)
        if not role:
            raise ValueError("角色不存在")

        # 删除旧权限
        await db.execute(
            delete(RolePermission).where(RolePermission.role_id == role_id)
        )

        # 插入新权限
        for permission_id in permission_ids:
            role_permission = RolePermission(
                role_id=role_id,
                permission_id=permission_id,
            )
            db.add(role_permission)

        await db.commit()

        # 清除相关用户缓存
        await RbacService._clear_role_users_cache(db, role_id)

        return True

    # ==================== 用户角色分配 ====================

    @staticmethod
    async def get_user_role_ids(db: AsyncSession, user_id: int) -> List[int]:
        """获取用户角色ID列表

        Args:
            db: 数据库会话
            user_id: 用户ID

        Returns:
            角色ID列表
        """
        result = await db.execute(
            select(UserRole.role_id).where(UserRole.user_id == user_id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def assign_roles_to_user(
        db: AsyncSession, user_id: int, role_ids: List[int]
    ) -> bool:
        """为用户分配角色

        Args:
            db: 数据库会话
            user_id: 用户ID
            role_ids: 角色ID列表

        Returns:
            是否分配成功
        """
        user = await db.get(User, user_id)
        if not user:
            raise ValueError("用户不存在")

        # 清除用户缓存
        await RbacService.clear_user_cache(user_id)

        # 删除旧角色
        await db.execute(
            delete(UserRole).where(UserRole.user_id == user_id)
        )

        # 插入新角色
        for role_id in role_ids:
            user_role = UserRole(
                user_id=user_id,
                role_id=role_id,
            )
            db.add(user_role)

        await db.commit()
        return True

    # ==================== 用户菜单 ====================

    @staticmethod
    async def get_user_menu_tree(db: AsyncSession, user_id: int) -> List[dict]:
        """获取用户可访问的权限列表（按 sort_order 排序）"""
        from src.models.user import Permission

        result = await db.execute(
            select(Permission)
            .where(Permission.status == True)
            .order_by(Permission.sort_order)
        )
        permissions = result.scalars().all()

        return [
            {
                "id": p.id,
                "permissionCode": p.code,
                "permissionName": p.name,
                "routePath": p.route_path,
                "sortOrder": p.sort_order,
            }
            for p in permissions
        ]

    # ==================== 辅助方法 ====================

    @staticmethod
    async def _clear_role_users_cache(db: AsyncSession, role_id: int):
        """清除拥有指定角色的所有用户的缓存

        Args:
            db: 数据库会话
            role_id: 角色ID
        """
        result = await db.execute(
            select(UserRole.user_id).where(UserRole.role_id == role_id)
        )
        user_ids = result.scalars().all()

        for user_id in user_ids:
            await RbacService.clear_user_cache(user_id)

    @staticmethod
    async def _clear_permission_users_cache(db: AsyncSession, permission_id: int):
        """清除拥有指定权限的所有用户的缓存

        Args:
            db: 数据库会话
            permission_id: 权限ID
        """
        # 查找所有拥有该权限的角色
        result = await db.execute(
            select(RolePermission.role_id).where(RolePermission.permission_id == permission_id)
        )
        role_ids = result.scalars().all()

        # 查找所有拥有这些角色的用户
        for role_id in role_ids:
            await RbacService._clear_role_users_cache(db, role_id)

    @staticmethod
    async def _reload_permission_map():
        """清除 Redis 权限路径缓存，下次请求时自动从 DB 重建"""
        try:
            from src.app.middleware.permission_middleware import PermissionMiddleware
            await PermissionMiddleware.invalidate_cache()
        except Exception as e:
            import logging
            logging.warning(f"清除权限缓存失败: {e}")
