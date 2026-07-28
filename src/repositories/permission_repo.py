"""Permission 数据访问层

职责：只做"读 / 写 ORM"，没有业务规则。
"""
from typing import List, Optional, Dict, Any

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import Permission, Role, RolePermission, User, UserRole


class PermissionRepository:
    """permission 表的数据访问层"""

    # =========================================================================
    # 基础查询
    # =========================================================================

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        permission_id: int,
    ) -> Optional[Permission]:
        """根据 ID 查询权限"""
        return await db.get(Permission, permission_id)

    @staticmethod
    async def get_by_code(
        db: AsyncSession,
        permission_code: str,
    ) -> Optional[Permission]:
        """根据权限编码查询权限"""
        result = await db.execute(
            select(Permission).where(Permission.permission_code == permission_code)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(
        db: AsyncSession,
        status: Optional[bool] = None,
    ) -> List[Permission]:
        """获取所有权限"""
        query = select(Permission)
        if status is not None:
            query = query.where(Permission.status == status)
        query = query.order_by(Permission.sort_order.asc())
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_group(
        db: AsyncSession,
        group_code: str,
        status: Optional[bool] = None,
    ) -> List[Permission]:
        """按分组获取权限"""
        query = select(Permission).where(Permission.group_code == group_code)
        if status is not None:
            query = query.where(Permission.status == status)
        query = query.order_by(Permission.sort_order.asc())
        result = await db.execute(query)
        return list(result.scalars().all())

    # =========================================================================
    # 写操作
    # =========================================================================

    @staticmethod
    async def insert(
        db: AsyncSession,
        permission: Permission,
    ) -> Permission:
        """新增权限"""
        db.add(permission)
        await db.flush()
        return permission

    @staticmethod
    async def update(
        db: AsyncSession,
        permission: Permission,
    ) -> Permission:
        """更新权限"""
        await db.flush()
        return permission

    @staticmethod
    async def delete_by_id(
        db: AsyncSession,
        permission_id: int,
    ) -> bool:
        """删除权限（级联删除关联）"""
        permission = await db.get(Permission, permission_id)
        if not permission:
            return False

        # 删除角色权限关联
        await db.execute(
            delete(RolePermission).where(RolePermission.permission_id == permission_id)
        )
        # 删除权限
        await db.delete(permission)
        await db.flush()
        return True

    # =========================================================================
    # 角色权限关联
    # =========================================================================

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
    async def assign_to_role(
        db: AsyncSession,
        role_id: int,
        permission_ids: List[int],
    ) -> None:
        """分配权限给角色（先删后加）"""
        # 删除现有权限关联
        await db.execute(
            delete(RolePermission).where(RolePermission.role_id == role_id)
        )
        # 添加新权限关联
        for permission_id in permission_ids:
            db.add(RolePermission(role_id=role_id, permission_id=permission_id))
        await db.flush()

    # =========================================================================
    # 菜单树相关
    # =========================================================================

    @staticmethod
    async def get_user_menu_tree(
        db: AsyncSession,
        user_id: int,
    ) -> List[Dict[str, Any]]:
        """获取用户菜单树（用于前端菜单渲染）"""
        result = await db.execute(
            select(Permission)
            .select_from(UserRole)
            .join(Role, UserRole.role_id == Role.id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, RolePermission.permission_id == Permission.id)
            .where(UserRole.user_id == user_id)
            .where(Role.status == True)
            .where(Permission.status == True)
            .where(Permission.api_path.isnot(None))
            .where(Permission.api_path != "")
        )
        permissions = result.scalars().all()

        # 按 group 分组
        tree_map: Dict[str, List[Dict[str, Any]]] = {}
        for p in permissions:
            group = p.group_code or "other"
            if group not in tree_map:
                tree_map[group] = []
            tree_map[group].append({
                "id": p.id,
                "permissionCode": p.permission_code,
                "permissionName": p.permission_name,
                "apiPath": p.api_path,
                "description": p.description,
            })

        # 转换为树结构
        tree = [
            {
                "groupCode": group_code,
                "groupName": _get_group_name(group_code),
                "permissions": perms,
            }
            for group_code, perms in tree_map.items()
        ]

        return tree

    @staticmethod
    async def get_path_permission(
        db: AsyncSession,
        path: str,
    ) -> Optional[str]:
        """根据 API 路径获取权限编码（用于权限校验）

        用于中间件的路径权限校验。
        """
        result = await db.execute(
            select(Permission.permission_code)
            .where(Permission.api_path == path)
            .where(Permission.status == True)
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return row

    # =========================================================================
    # 缓存清理（关联查询）
    # =========================================================================

    @staticmethod
    async def get_users_by_permission(
        db: AsyncSession,
        permission_id: int,
    ) -> List[User]:
        """获取拥有某权限的所有用户"""
        result = await db.execute(
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(RolePermission, RolePermission.role_id == UserRole.role_id)
            .where(RolePermission.permission_id == permission_id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_permission_user_ids(
        db: AsyncSession,
        permission_id: int,
    ) -> List[int]:
        """获取拥有某权限的所有用户 ID"""
        result = await db.execute(
            select(User.id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(RolePermission, RolePermission.role_id == UserRole.role_id)
            .where(RolePermission.permission_id == permission_id)
        )
        return [row[0] for row in result.all()]


def _get_group_name(group_code: str) -> str:
    """获取分组显示名称"""
    group_names = {
        "user": "用户管理",
        "role": "角色管理",
        "permission": "权限管理",
        "template": "模板管理",
        "rule": "规则管理",
        "system": "系统设置",
        "other": "其他",
    }
    return group_names.get(group_code, group_code)


__all__ = ["PermissionRepository"]
