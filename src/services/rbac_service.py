"""RBAC 核心服务

实现基于角色的访问控制（Role-Based Access Control），包括：
- 用户角色和权限的获取（含缓存）
- 角色管理（CRUD）
- 权限管理（CRUD）
- 用户角色分配
- 角色权限分配

超管白名单（SYSTEM_ACCOUNTS）由 src.infra.config.is_system_account 统一管理。
"""
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_
from sqlalchemy.orm import selectinload
import json
from src.models.user import User, Role, Permission, UserRole, RolePermission
from src.infra.redis import get_redis
from src.infra.database import AsyncSessionLocal
from src.app.schemas.errors import BadRequestError, NotFoundError, ConflictError, ForbiddenError

class RbacService:
    """RBAC 核心服务"""
    CACHE_TTL = 300  # 5 分钟（统一缓存策略：所有 user 级 rbac/status 缓存都用这个 TTL）
    USER_ROLES_KEY = 'rbac:user:roles:'
    USER_PERMS_KEY = 'rbac:user:perms:'
    USER_STATUS_KEY = 'status:user:'  # account active flag: "1" / "0"
    API_PERM_KEY_PREFIX = 'rbac:api:'

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
        cache_key = f'{RbacService.USER_ROLES_KEY}{user_id}'
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)
        result = await db.execute(select(Role.role_code).join(UserRole, Role.id == UserRole.role_id).where(UserRole.user_id == user_id))
        roles = list(result.scalars().all())
        await redis.setex(cache_key, RbacService.CACHE_TTL, json.dumps(roles))
        return roles

    @staticmethod
    async def get_path_permission(path: str) -> Optional[str]:
        """查询路径所需权限码（精确匹配优先，回退动态路由前缀匹配）

        例：/api/system/role/5  →  匹配 /api/system/role/{id}  →  返回 role:read
        """
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Permission.permission_code).where(Permission.api_path == path).where(Permission.status == True).limit(1))
            code: Optional[str] = result.scalar_one_or_none()
            if code:
                return code
            result = await db.execute(select(Permission.permission_code, Permission.api_path).where(Permission.api_path.isnot(None)).where(Permission.status == True))
            req_parts = [p for p in path.split('/') if p]
            for perm_code, route_path in result.all():
                if '{' not in route_path:
                    continue
                tmpl_parts = [p for p in route_path.split('/') if p]
                if len(tmpl_parts) != len(req_parts):
                    continue
                if all((t.startswith('{') or t == r for t, r in zip(tmpl_parts, req_parts))):
                    return perm_code
        return None

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
        return any((role in user_roles for role in required_roles))

    @staticmethod
    async def clear_user_cache(user_id: int):
        """清除用户缓存（rbac + status）

        Args:
            user_id: 用户ID
        """
        redis = await get_redis()
        await redis.delete(f'{RbacService.USER_ROLES_KEY}{user_id}')
        await redis.delete(f'{RbacService.USER_PERMS_KEY}{user_id}')
        await redis.delete(f'{RbacService.USER_STATUS_KEY}{user_id}')

    @staticmethod
    async def clear_user_status_cache(user_id: int):
        """仅清除用户状态缓存（账号 active flag）。

        适用于：仅修改了账号 status 字段（如禁用/启用），没有改 rbac。
        """
        redis = await get_redis()
        await redis.delete(f'{RbacService.USER_STATUS_KEY}{user_id}')

    @staticmethod
    async def invalidate_all_user_caches():
        """清除所有 rbac:user:* 和 status:user:* 缓存。

        用于：RBAC 硬重置（清空所有 role/permission）后。
        ⚠️ 使用 SCAN 遍历避免 KEYS 阻塞生产 Redis。
        """
        redis = await get_redis()
        patterns = ["rbac:user:*", "status:user:*"]
        for pattern in patterns:
            cursor = 0
            while True:
                cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=200)
                if keys:
                    await redis.delete(*keys)
                if cursor == 0:
                    break

    @staticmethod
    async def clear_api_cache(api_path: str):
        """清除指定接口的权限缓存"""
        redis = await get_redis()
        cache_key = f'rbac:api:perm:{api_path}'
        await redis.delete(cache_key)

    @staticmethod
    async def get_all_roles(db: AsyncSession) -> List[Role]:
        """获取所有角色

        Args:
            db: 数据库会话

        Returns:
            角色列表
        """
        result = await db.execute(select(Role).order_by(Role.sort_order, Role.id))
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
        result = await db.execute(select(Role).where(Role.role_code == role_code))
        return result.scalar_one_or_none()

    @staticmethod
    async def create_role_from_request(db: AsyncSession, req) -> Role:
        """根据 RoleCreateRequest 创建角色"""
        existing = await RbacService.get_role_by_code(db, req.roleCode)
        if existing:
            raise ConflictError(f'角色代码已存在: {req.roleCode}')
        role = req.to_orm()
        db.add(role)
        await db.commit()
        await db.refresh(role)
        return role

    @staticmethod
    async def update_role_from_request(db: AsyncSession, req) -> Optional[Role]:
        """根据 RoleUpdateRequest 更新角色（req.apply_to 处理字段映射）。"""
        role = await db.get(Role, req.id)
        if not role:
            return None
        modified = req.apply_to(role)
        if not modified:
            return role
        await db.commit()
        await db.refresh(role)
        await RbacService._clear_role_users_cache(db, req.id)
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
        if role.is_system:
            raise ForbiddenError(f'系统角色不可删除: {role.role_code}')
        await RbacService._clear_role_users_cache(db, role_id)
        await db.execute(delete(UserRole).where(UserRole.role_id == role_id))
        await db.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
        await db.delete(role)
        await db.commit()
        return True

    @staticmethod
    async def get_all_permissions(db: AsyncSession) -> List[Permission]:
        """获取所有权限

        Args:
            db: 数据库会话

        Returns:
            权限列表
        """
        result = await db.execute(select(Permission).order_by(Permission.sort_order, Permission.id))
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
        result = await db.execute(select(Permission).where(Permission.permission_code == code))
        return result.scalar_one_or_none()

    @staticmethod
    async def create_permission_from_request(db: AsyncSession, req) -> Permission:
        """根据 PermissionCreateRequest 创建权限"""
        existing = await RbacService.get_permission_by_code(db, req.permissionCode)
        if existing:
            raise ConflictError(f'权限代码已存在: {req.permissionCode}')
        permission = req.to_orm()
        db.add(permission)
        await db.commit()
        await db.refresh(permission)
        if permission.api_path:
            await RbacService.clear_api_cache(permission.api_path)
        return permission

    @staticmethod
    async def update_permission_from_request(db: AsyncSession, req) -> Optional[Permission]:
        """根据 PermissionUpdateRequest 更新权限（req.apply_to 处理字段映射）。

        注意：api_path 缓存失效需要分别清旧 path / 新 path。
        """
        permission = await db.get(Permission, req.id)
        if not permission:
            return None
        api_path_before = permission.api_path
        if not req.apply_to(permission):
            return permission
        await db.commit()
        await db.refresh(permission)
        await RbacService._clear_permission_users_cache(db, req.id)
        if api_path_before:
            await RbacService.clear_api_cache(api_path_before)
        if permission.api_path and permission.api_path != api_path_before:
            await RbacService.clear_api_cache(permission.api_path)
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
        api_path = permission.api_path
        await RbacService._clear_permission_users_cache(db, permission_id)
        await db.execute(delete(RolePermission).where(RolePermission.permission_id == permission_id))
        await db.delete(permission)
        await db.commit()
        if api_path:
            await RbacService.clear_api_cache(api_path)
        return True

    @staticmethod
    async def get_role_permissions(db: AsyncSession, role_id: int) -> List[Permission]:
        """获取角色的权限列表

        Args:
            db: 数据库会话
            role_id: 角色ID

        Returns:
            权限列表
        """
        result = await db.execute(select(Permission).join(RolePermission, Permission.id == RolePermission.permission_id).where(RolePermission.role_id == role_id).where(Permission.status == True))
        return list(result.scalars().all())

    @staticmethod
    async def assign_permissions_to_role_from_request(db: AsyncSession, req) -> bool:
        """根据 RolePermissionAssignRequest 分配权限"""
        role = await db.get(Role, req.roleId)
        if not role:
            raise NotFoundError(f'角色不存在: id={req.roleId}')
        await db.execute(delete(RolePermission).where(RolePermission.role_id == req.roleId))
        for permission_id in req.permissionIds:
            role_permission = RolePermission(role_id=req.roleId, permission_id=permission_id)
            db.add(role_permission)
        await db.commit()
        await RbacService._clear_role_users_cache(db, req.roleId)
        return True

    @staticmethod
    async def get_user_role_ids(db: AsyncSession, user_id: int) -> List[int]:
        result = await db.execute(select(UserRole.role_id).where(UserRole.user_id == user_id))
        return list(result.scalars().all())

    @staticmethod
    async def assign_roles_to_user(db: AsyncSession, user_id: int, role_ids: List[int]) -> bool:
        user = await db.get(User, user_id)
        if not user:
            raise NotFoundError(f'用户不存在: id={user_id}')
        await db.execute(delete(UserRole).where(UserRole.user_id == user_id))
        for role_id in role_ids:
            user_role = UserRole(user_id=user_id, role_id=role_id)
            db.add(user_role)
        await db.commit()
        await RbacService.clear_user_cache(user_id)
        return True

    @staticmethod
    async def get_user_menu_tree(db: AsyncSession, user_permissions: List[str]) -> List[dict]:
        """获取用户可访问的权限列表（按用户权限集合过滤，按 sort_order 排序）

        Args:
            db: 数据库会话
            user_permissions: 当前用户拥有的权限码列表，"*" 表示全部
        """
        stmt = select(Permission).where(Permission.status == True).order_by(Permission.sort_order)
        if '*' not in user_permissions:
            stmt = stmt.where(Permission.permission_code.in_(user_permissions))
        result = await db.execute(stmt)
        permissions = result.scalars().all()
        return [{'id': p.id, 'permissionCode': p.permission_code, 'permissionName': p.permission_name, 'routePath': p.api_path, 'sortOrder': p.sort_order} for p in permissions]

    @staticmethod
    async def _clear_role_users_cache(db: AsyncSession, role_id: int):
        """清除拥有指定角色的所有用户的缓存

        Args:
            db: 数据库会话
            role_id: 角色ID
        """
        result = await db.execute(select(UserRole.user_id).where(UserRole.role_id == role_id))
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
        result = await db.execute(select(RolePermission.role_id).where(RolePermission.permission_id == permission_id))
        role_ids = result.scalars().all()
        for role_id in role_ids:
            await RbacService._clear_role_users_cache(db, role_id)