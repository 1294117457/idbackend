"""User 数据访问层

职责：只做"读 / 写 ORM"，没有业务规则。
"""
from typing import List, Optional, Tuple, Dict, Any

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User, UserStatus, UserRole, Role, Permission, RolePermission


class UserRepository:
    """user 表的数据访问层"""

    # =========================================================================
    # 基础查询
    # =========================================================================

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        user_id: int,
    ) -> Optional[User]:
        """根据 ID 查询用户"""
        return await db.get(User, user_id)

    @staticmethod
    async def get_by_username(
        db: AsyncSession,
        username: str,
    ) -> Optional[User]:
        """根据用户名查询用户"""
        result = await db.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    # =========================================================================
    # 分页查询
    # =========================================================================

    @staticmethod
    async def list_paged(
        db: AsyncSession,
        username: Optional[str] = None,
        full_name: Optional[str] = None,
        major: Optional[str] = None,
        grade: Optional[int] = None,
        graduation_year: Optional[int] = None,
        enrollment_year: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[User], int]:
        """分页查询用户列表"""
        query = select(User)

        if username:
            query = query.where(User.username.ilike(f"%{username}%"))
        if full_name:
            query = query.where(User.full_name.ilike(f"%{full_name}%"))
        if major:
            query = query.where(User.major.ilike(f"%{major}%"))
        if grade is not None:
            query = query.where(User.grade == grade)
        if graduation_year is not None:
            query = query.where(User.graduation_year == graduation_year)
        if enrollment_year is not None:
            query = query.where(User.enrollment_year == enrollment_year)

        count_stmt = select(func.count()).select_from(query.subquery())
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        query = (
            query.order_by(User.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await db.execute(query)
        return list(result.scalars().all()), total

    # =========================================================================
    # 写操作
    # =========================================================================

    @staticmethod
    async def insert(
        db: AsyncSession,
        user: User,
    ) -> User:
        """新增用户"""
        db.add(user)
        await db.flush()
        return user

    @staticmethod
    async def delete_by_id(
        db: AsyncSession,
        user_id: int,
    ) -> bool:
        """根据 ID 删除用户，返回是否删除成功"""
        user = await db.get(User, user_id)
        if not user:
            return False
        await db.delete(user)
        await db.flush()
        return True

    @staticmethod
    async def update_status(
        db: AsyncSession,
        user: User,
        status: str,
    ) -> User:
        """更新用户状态"""
        user.status = status
        await db.flush()
        return user

    @staticmethod
    async def update_fields(
        db: AsyncSession,
        user: User,
        data: Dict[str, Any],
        forbidden: Optional[set] = None,
    ) -> bool:
        """更新用户字段

        Args:
            db: 数据库会话
            user: 用户 ORM 对象
            data: 待更新字段字典
            forbidden: 禁止更新的字段集合

        Returns:
            是否有修改
        """
        if forbidden is None:
            forbidden = {
                "id", "username", "student_id", "score_info",
                "password", "status", "created_at", "updated_at"
            }

        modified = False
        for key, value in data.items():
            if key in forbidden:
                continue
            if hasattr(user, key):
                current = getattr(user, key)
                if current != value:
                    setattr(user, key, value)
                    modified = True

        if modified:
            await db.flush()
        return modified

    @staticmethod
    async def update_extra_info(
        db: AsyncSession,
        user: User,
        extra_info: dict,
    ) -> User:
        """更新用户扩展信息（合并）"""
        current = dict(user.extra_info or {})
        current.update(extra_info)
        user.extra_info = current
        await db.flush()
        return user

    # =========================================================================
    # 用户角色关联
    # =========================================================================

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
    async def assign_roles(
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
    # RBAC 联合查询（供 Middleware/Service 使用）
    # =========================================================================

    @staticmethod
    async def load_user_rbac_data(
        db: AsyncSession,
        user_id: int,
    ) -> Optional[Dict[str, Any]]:
        """加载用户完整 RBAC 数据（用于权限校验）

        返回格式:
            {
                "user_id": int,
                "username": str,
                "is_admin": bool,
                "roles": [{"roleCode": str, "roleName": str}, ...],
                "permissions": [str, ...],
            }
        """
        user = await db.get(User, user_id)
        if not user:
            return None

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

    # =========================================================================
    # 成绩相关
    # =========================================================================

    @staticmethod
    async def get_scores_with_category(
        db: AsyncSession,
        user_id: int,
    ) -> dict:
        """获取用户积分（从 score_info 读取，含分类信息）

        v4.6 适配：score_info 持久化字段从 categories 字典改为 scores 字典
        """
        user = await db.get(User, user_id)
        if not user or not user.score_info:
            return {"categories": {}, "total": 0.0, "calculated_at": None}

        score_info = user.score_info or {}
        scores_dict = score_info.get("scores") or {}

        # 从 template_category 取 name
        categories: Dict[str, Dict[str, Any]] = {}
        if scores_dict:
            from src.models.template_category import TemplateCategory
            result = await db.execute(
                select(TemplateCategory).where(
                    TemplateCategory.id.in_([int(cid) for cid in scores_dict.keys()])
                )
            )
            for row in result.scalars().all():
                cat_id_str = str(row.id)
                if cat_id_str in scores_dict:
                    s = scores_dict[cat_id_str]
                    categories[cat_id_str] = {
                        "name": row.name,
                        "score": s.get("score", 0.0),
                        "max": float(row.max_score) if row.max_score is not None else None,
                    }

        return {
            "categories": categories,
            "total": score_info.get("total", 0.0),
            "calculated_at": score_info.get("calculated_at"),
        }


__all__ = ["UserRepository"]
