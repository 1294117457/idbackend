"""用户服务"""

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Dict, Any

from src.models import User, Role, Permission, Application
from src.models.user import UserRole, RolePermission, UserStatus
from src.infra.jwt import hash_password
from src.infra.database import AsyncSessionLocal
from src.app.schemas.errors import NotFoundError, ConflictError


class UserService:
    """用户服务

    Service 层签名约定：
    - 写接口统一接 DTO Request 对象（路由不展开字段）
    - 业务异常统一用 BusinessError 子类（见 src.app.schemas.errors）
    - 单字段副作用由 service 内部直接 ORM 写回，不走 DTO
    """

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
    async def get_user_by_id_or_raise(
        db: AsyncSession,
        user_id: int,
    ) -> User:
        """根据ID获取用户；找不到抛 NotFoundError（路由层无 try/except 风格走这里）"""
        user = await UserService.get_user_by_id(db, user_id)
        if user is None:
            raise NotFoundError(f"用户不存在: id={user_id}")
        return user

    @staticmethod
    async def get_user_by_username(
        db: AsyncSession,
        username: str,
    ) -> Optional[User]:
        """根据用户名获取用户"""
        result = await db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    @staticmethod
    async def update_user_from_request(
        db: AsyncSession,
        user_id: int,
        req,
    ) -> User:
        """通用：DTO 请求 → ORM 写回（req.apply_to 负责字段映射与"是否修改"判断）。

        找不到用户抛 NotFoundError；不修改返回原对象（不 commit）。
        """
        user = await UserService.get_user_by_id_or_raise(db, user_id)
        modified = req.apply_to(user)
        if modified:
            await db.commit()
            await db.refresh(user)
        return user

    @staticmethod
    async def get_user_scores(
        db: AsyncSession,
        user_id: int,
    ) -> dict:
        """获取用户积分（从 score_info 读取）

        如果 score_info 为空，返回空结构。
        """
        user = await UserService.get_user_by_id(db, user_id)
        if not user or not user.score_info:
            return {"categories": {}, "total": 0.0}
        return {
            "categories": user.score_info.get("categories", {}),
            "total": user.score_info.get("total", 0.0),
            "calculated_at": user.score_info.get("calculated_at"),
        }

    @staticmethod
    async def list_users(
        db: AsyncSession,
        req,
    ) -> tuple[List[User], int]:
        """获取用户列表（req: UserQueryRequest，支持多字段过滤 + 分页）"""
        query = select(User)

        if req.username:
            query = query.where(User.username.ilike(f"%{req.username}%"))
        if req.fullName:
            query = query.where(User.full_name.ilike(f"%{req.fullName}%"))
        if req.major:
            query = query.where(User.major.ilike(f"%{req.major}%"))
        if req.grade is not None:
            query = query.where(User.grade == req.grade)
        if req.graduationYear is not None:
            query = query.where(User.graduation_year == req.graduationYear)
        if req.enrollmentYear is not None:
            query = query.where(User.enrollment_year == req.enrollmentYear)

        count_stmt = select(func.count()).select_from(query.subquery())
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        query = (
            query.order_by(User.id.desc())
            .offset((req.pageNum - 1) * req.pageSize)
            .limit(req.pageSize)
        )
        result = await db.execute(query)
        users = result.scalars().all()
        return list(users), total

    @staticmethod
    async def create_user(
        db: AsyncSession,
        username: str,
        password: str,
    ) -> User:
        """创建用户（service 内部创建；路由侧传 password 时也走这里）

        业务校验：用户名冲突 → 抛 ConflictError
        """
        existing = await UserService.get_user_by_username(db, username)
        if existing:
            raise ConflictError(f"用户名已存在: {username}")

        user = User(
            username=username,
            password=hash_password(password),
            status=UserStatus.ACTIVE.value,
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
        user = await UserService.get_user_by_id(db, user_id)
        if not user:
            return False
        await db.delete(user)
        await db.commit()
        return True