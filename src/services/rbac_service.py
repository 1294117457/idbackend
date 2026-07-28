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
from src.repositories.role_repo import RoleRepository
from src.repositories.permission_repo import PermissionRepository
from src.app.schemas.errors import BadRequestError, NotFoundError, ConflictError, ForbiddenError


class RbacService:
    """RBAC 核心服务"""
    CACHE_TTL = 300  # 5 分钟
    USER_ROLES_KEY = 'rbac:user:roles:'
    USER_PERMS_KEY = 'rbac:user:perms:'
    USER_STATUS_KEY = 'status:user:'
    API_PERM_KEY_PREFIX = 'rbac:api:'

    # =========================================================================
    # 用户角色权限查询
    # =========================================================================

    @staticmethod
    async def get_user_roles(db: AsyncSession, user_id: int) -> List[str]:
        """获取用户角色列表（含缓存）"""
        redis = await get_redis()
        cache_key = f'{RbacService.USER_ROLES_KEY}{user_id}'
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)

        roles = await RoleRepository.get_user_roles(db, user_id)
        role_codes = [r.role_code for r in roles]
        await redis.setex(cache_key, RbacService.CACHE_TTL, json.dumps(role_codes))
        return role_codes

    @staticmethod
    async def get_path_permission(db: AsyncSession, path: str) -> Optional[str]:
        """查询路径所需权限码（精确匹配优先，回退动态路由前缀匹配）"""
        # 精确匹配
        code = await PermissionRepository.get_path_permission(db, path)
        if code:
            return code

        # 动态路由匹配
        all_permissions = await PermissionRepository.get_all(db, status=True)
        req_parts = [p for p in path.split('/') if p]

        for perm in all_permissions:
            if not perm.api_path or '{' not in perm.api_path:
                continue
            tmpl_parts = [p for p in perm.api_path.split('/') if p]
            if len(tmpl_parts) != len(req_parts):
                continue
            if all((t.startswith('{') or t == r for t, r in zip(tmpl_parts, req_parts))):
                return perm.permission_code

        return None

    @staticmethod
    async def has_any_role(db: AsyncSession, user_id: int, *required_roles: str) -> bool:
        """检查用户是否拥有指定角色（任意一个即可）"""
        user_roles = await RbacService.get_user_roles(db, user_id)
        return any((role in user_roles for role in required_roles))

    # =========================================================================
    # 缓存清理
    # =========================================================================

    @staticmethod
    async def clear_user_cache(user_id: int):
        """清除用户缓存"""
        redis = await get_redis()
        await redis.delete(f'{RbacService.USER_ROLES_KEY}{user_id}')
        await redis.delete(f'{RbacService.USER_PERMS_KEY}{user_id}')
        await redis.delete(f'{RbacService.USER_STATUS_KEY}{user_id}')

    @staticmethod
    async def clear_user_status_cache(user_id: int):
        """仅清除用户状态缓存"""
        redis = await get_redis()
        await redis.delete(f'{RbacService.USER_STATUS_KEY}{user_id}')

    @staticmethod
    async def invalidate_all_user_caches():
        """清除所有 rbac:user:* 和 status:user:* 缓存"""
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

    # =========================================================================
    # 角色管理
    # =========================================================================

    @staticmethod
    async def get_all_roles(db: AsyncSession) -> List[Role]:
        """获取所有角色"""
        return await RoleRepository.get_all(db)

    @staticmethod
    async def get_role_by_id(db: AsyncSession, role_id: int) -> Optional[Role]:
        """根据ID获取角色"""
        return await RoleRepository.get_by_id(db, role_id)

    @staticmethod
    async def get_role_by_code(db: AsyncSession, role_code: str) -> Optional[Role]:
        """根据代码获取角色"""
        return await RoleRepository.get_by_code(db, role_code)

    @staticmethod
    async def create_role_from_request(db: AsyncSession, req) -> Role:
        """根据 RoleCreateRequest 创建角色"""
        existing = await RoleRepository.get_by_code(db, req.roleCode)
        if existing:
            raise ConflictError(f'角色代码已存在: {req.roleCode}')
        role = req.to_orm()
        return await RoleRepository.insert(db, role)

    @staticmethod
    async def update_role_from_request(db: AsyncSession, req) -> Optional[Role]:
        """根据 RoleUpdateRequest 更新角色"""
        role = await RoleRepository.get_by_id(db, req.id)
        if not role:
            return None
        modified = req.apply_to(role)
        if not modified:
            return role
        await RoleRepository.update(db, role)
        await RbacService._clear_role_users_cache(db, req.id)
        return role

    @staticmethod
    async def delete_role(db: AsyncSession, role_id: int) -> bool:
        """删除角色"""
        role = await RoleRepository.get_by_id(db, role_id)
        if not role:
            return False
        if role.is_system:
            raise ForbiddenError(f'系统角色不可删除: {role.role_code}')
        await RbacService._clear_role_users_cache(db, role_id)
        return await RoleRepository.delete_by_id(db, role_id)

    # =========================================================================
    # 权限管理
    # =========================================================================

    @staticmethod
    async def get_all_permissions(db: AsyncSession) -> List[Permission]:
        """获取所有权限"""
        return await PermissionRepository.get_all(db)

    @staticmethod
    async def get_permission_by_id(db: AsyncSession, permission_id: int) -> Optional[Permission]:
        """根据ID获取权限"""
        return await PermissionRepository.get_by_id(db, permission_id)

    @staticmethod
    async def get_permission_by_code(db: AsyncSession, code: str) -> Optional[Permission]:
        """根据代码获取权限"""
        return await PermissionRepository.get_by_code(db, code)

    @staticmethod
    async def create_permission_from_request(db: AsyncSession, req) -> Permission:
        """根据 PermissionCreateRequest 创建权限"""
        existing = await PermissionRepository.get_by_code(db, req.permissionCode)
        if existing:
            raise ConflictError(f'权限代码已存在: {req.permissionCode}')
        permission = req.to_orm()
        result = await PermissionRepository.insert(db, permission)
        if result.api_path:
            await RbacService.clear_api_cache(result.api_path)
        return result

    @staticmethod
    async def update_permission_from_request(db: AsyncSession, req) -> Optional[Permission]:
        """根据 PermissionUpdateRequest 更新权限"""
        permission = await PermissionRepository.get_by_id(db, req.id)
        if not permission:
            return None
        api_path_before = permission.api_path
        if not req.apply_to(permission):
            return permission

        await PermissionRepository.update(db, permission)
        await RbacService._clear_permission_users_cache(db, req.id)
        if api_path_before:
            await RbacService.clear_api_cache(api_path_before)
        if permission.api_path and permission.api_path != api_path_before:
            await RbacService.clear_api_cache(permission.api_path)
        return permission

    @staticmethod
    async def delete_permission(db: AsyncSession, permission_id: int) -> bool:
        """删除权限"""
        permission = await PermissionRepository.get_by_id(db, permission_id)
        if not permission:
            return False
        api_path = permission.api_path
        await RbacService._clear_permission_users_cache(db, permission_id)
        result = await PermissionRepository.delete_by_id(db, permission_id)
        if result and api_path:
            await RbacService.clear_api_cache(api_path)
        return result

    # =========================================================================
    # 角色权限分配
    # =========================================================================

    @staticmethod
    async def get_role_permissions(db: AsyncSession, role_id: int) -> List[Permission]:
        """获取角色的权限列表"""
        return await PermissionRepository.get_role_permissions(db, role_id)

    @staticmethod
    async def assign_permissions_to_role_from_request(db: AsyncSession, req) -> bool:
        """根据 RolePermissionAssignRequest 分配权限"""
        role = await RoleRepository.get_by_id(db, req.roleId)
        if not role:
            raise NotFoundError(f'角色不存在: id={req.roleId}')
        await PermissionRepository.assign_to_role(db, req.roleId, req.permissionIds)
        await RbacService._clear_role_users_cache(db, req.roleId)
        return True

    @staticmethod
    async def get_user_role_ids(db: AsyncSession, user_id: int) -> List[int]:
        """获取用户角色 ID 列表"""
        return await RoleRepository.get_user_role_ids(db, user_id)

    @staticmethod
    async def assign_roles_to_user(db: AsyncSession, user_id: int, role_ids: List[int]) -> bool:
        """分配用户角色"""
        user = await RoleRepository.get_by_id(db, user_id)
        if not user:
            # UserRepository.get_by_id 已经在上面调用过了，这里用另一种方式
            from src.repositories.user_repo import UserRepository
            user = await UserRepository.get_by_id(db, user_id)
            if not user:
                raise NotFoundError(f'用户不存在: id={user_id}')
        await RoleRepository.assign_roles_to_user(db, user_id, role_ids)
        await RbacService.clear_user_cache(user_id)
        return True

    @staticmethod
    async def get_user_menu_tree(db: AsyncSession, user_permissions: List[str]) -> List[dict]:
        """获取用户可访问的权限列表"""
        if '*' in user_permissions:
            permissions = await PermissionRepository.get_all(db, status=True)
        else:
            from src.repositories.permission_repo import PermissionRepository
            permissions = []
            for code in user_permissions:
                perm = await PermissionRepository.get_by_code(db, code)
                if perm:
                    permissions.append(perm)

        return [
            {
                'id': p.id,
                'permissionCode': p.permission_code,
                'permissionName': p.permission_name,
                'routePath': p.api_path,
                'sortOrder': p.sort_order
            }
            for p in sorted(permissions, key=lambda x: x.sort_order)
        ]

    # =========================================================================
    # 缓存清理（内部方法）
    # =========================================================================

    @staticmethod
    async def _clear_role_users_cache(db: AsyncSession, role_id: int):
        """清除拥有指定角色的所有用户的缓存"""
        user_ids = await RoleRepository.get_role_user_ids(db, role_id)
        for user_id in user_ids:
            await RbacService.clear_user_cache(user_id)

    @staticmethod
    async def _clear_permission_users_cache(db: AsyncSession, permission_id: int):
        """清除拥有指定权限的所有用户的缓存"""
        user_ids = await PermissionRepository.get_permission_user_ids(db, permission_id)
        for user_id in user_ids:
            await RbacService.clear_user_cache(user_id)
