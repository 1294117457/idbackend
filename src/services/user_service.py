"""用户服务"""

from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Dict, Any, Tuple
import json
import secrets
import string

from src.models import User, Role, Permission, Application
from src.models.user import UserRole, RolePermission, UserStatus
from src.infra.jwt import hash_password
from src.infra.redis import get_redis
from src.repositories.user_repo import UserRepository
from src.repositories.role_repo import RoleRepository
from src.app.schemas.errors import NotFoundError, ConflictError


def generate_password(length: int = 12) -> str:
    """生成随机密码"""
    return "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(length)
    )


class UserService:
    @staticmethod
    async def verify_account_active(db: AsyncSession, user_id: int) -> bool:
        """验证账号是否激活（需要 db 参数）

        从数据库查询用户状态，优先使用缓存。
        """
        redis = await get_redis()
        cache_key = f"status:user:{user_id}"
        cached = await redis.get(cache_key)
        if cached is not None:
            return cached == "1"

        user = await UserRepository.get_by_id(db, user_id)
        is_active = user is not None and user.status == UserStatus.ACTIVE.value

        await redis.setex(cache_key, 300, "1" if is_active else "0")
        return is_active

    @staticmethod
    async def load_user_rbac(db: AsyncSession, user_id: int) -> Optional[Dict[str, Any]]:
        """加载用户完整 RBAC 数据（需要 db 参数）

        从数据库查询用户角色和权限，优先使用缓存。
        """
        redis = await get_redis()
        cache_key = f"rbac:user:full:{user_id}"
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)

        rbac_data = await UserRepository.load_user_rbac_data(db, user_id)
        if rbac_data:
            await redis.setex(cache_key, 300, json.dumps(rbac_data, ensure_ascii=False))
        return rbac_data

    @staticmethod
    async def load_user_auth_info(db: AsyncSession, user_id: int) -> Optional[Dict[str, Any]]:
        """加载用户认证信息（验证激活状态 + 加载 RBAC）"""
        if not await UserService.verify_account_active(db, user_id):
            return None

        result = await UserService.load_user_rbac(db, user_id)
        if result is None:
            return {
                "user_id": user_id,
                "username": "",
                "is_admin": False,
                "roles": [],
                "permissions": [],
            }
        return result

    @staticmethod
    async def get_user_by_id(
        db: AsyncSession,
        user_id: int,
    ) -> Optional[User]:
        """根据ID获取用户"""
        return await UserRepository.get_by_id(db, user_id)

    @staticmethod
    async def get_user_by_id_or_raise(
        db: AsyncSession,
        user_id: int,
    ) -> User:
        """根据ID获取用户；找不到抛 NotFoundError"""
        user = await UserRepository.get_by_id(db, user_id)
        if user is None:
            raise NotFoundError(f"用户不存在: id={user_id}")
        return user

    @staticmethod
    async def get_user_by_username(
        db: AsyncSession,
        username: str,
    ) -> Optional[User]:
        """根据用户名获取用户"""
        return await UserRepository.get_by_username(db, username)

    @staticmethod
    async def update_user_from_request(
        db: AsyncSession,
        user_id: int,
        req,
    ) -> User:
        """通用：DTO 请求 → ORM 写回"""
        user = await UserService.get_user_by_id_or_raise(db, user_id)
        modified = req.apply_to(user)
        if not modified:
            return user
        return user

    @staticmethod
    async def get_user_scores(
        db: AsyncSession,
        user_id: int,
    ) -> dict:
        """获取用户积分"""
        return await UserRepository.get_scores_with_category(db, user_id)

    @staticmethod
    async def list_users(
        db: AsyncSession,
        req,
    ) -> tuple[List[User], int]:
        """获取用户列表（req: UserQueryRequest）"""
        return await UserRepository.list_paged(
            db,
            username=req.username,
            full_name=req.fullName,
            major=req.major,
            grade=req.grade,
            graduation_year=req.graduationYear,
            enrollment_year=req.enrollmentYear,
            page=req.pageNum,
            page_size=req.pageSize,
        )

    @staticmethod
    async def create_user(
        db: AsyncSession,
        username: str,
        password: str,
    ) -> User:
        """创建用户"""
        existing = await UserRepository.get_by_username(db, username)
        if existing:
            raise ConflictError(f"用户名已存在: {username}")

        user = User(
            username=username,
            password=hash_password(password),
            status=UserStatus.ACTIVE.value,
        )
        return await UserRepository.insert(db, user)

    @staticmethod
    async def delete_user(
        db: AsyncSession,
        user_id: int,
    ) -> bool:
        """删除用户"""
        success = await UserRepository.delete_by_id(db, user_id)
        if success:
            await UserService.clear_user_cache(user_id)
        return success

    @staticmethod
    async def update_user_status(
        db: AsyncSession,
        user_id: int,
        status: str,
    ) -> User:
        """更新用户状态"""
        user = await UserService.get_user_by_id_or_raise(db, user_id)
        await UserRepository.update_status(db, user, status)
        await UserService.clear_user_status_cache(user_id)
        return user

    @staticmethod
    async def create_user_with_password_gen(
        db: AsyncSession,
        username: str,
        password: Optional[str] = None,
        role_code: Optional[str] = None,
    ) -> Tuple[User, str]:
        """创建用户（可选自动生成密码），返回 (User, raw_password)"""
        from src.services.rbac_service import RbacService

        raw_password = password if password else generate_password()
        user = await UserService.create_user(db, username, raw_password)

        if role_code:
            role = await RbacService.get_role_by_code(db, role_code)
            if role:
                await RbacService.assign_roles_to_user(db, user.id, [role.id])

        return user, raw_password

    @staticmethod
    async def batch_create_users(
        db: AsyncSession,
        usernames: List[str],
    ) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        """批量创建用户，返回 (created, failed)"""
        created: List[Dict[str, str]] = []
        failed: List[Dict[str, str]] = []

        for username in usernames:
            try:
                raw_password = generate_password()
                user = await UserService.create_user(db, username, raw_password)
                created.append({"username": username, "password": raw_password})
            except ConflictError:
                failed.append({"username": username, "reason": "用户已存在"})
            except Exception as e:
                failed.append({"username": username, "reason": str(e)})

        return created, failed

    @staticmethod
    async def list_users_with_roles(
        db: AsyncSession,
        req,
    ) -> Tuple[List[User], int, Dict[int, List[str]]]:
        """获取用户列表（含角色）

        性能优化（v1）：用一次 IN 查询批量获取角色映射，避免 N+1。
        旧实现对每页每个用户单独调用 RbacService.get_user_roles（50 用户=50 次 SQL）。
        现实现保持 Redis 缓存语义（缓存命中时不查 DB）。
        """
        from src.repositories.role_repo import RoleRepository

        users, total = await UserService.list_users(db, req)

        if not users:
            return users, total, {}

        user_ids = [u.id for u in users]
        # 优先用批量查询（1 次 SQL）；
        # 如果未来需要在列表页保持 Redis 缓存语义，可改为：
        #   1) 批量 keys 查 Redis 命中
        #   2) 未命中 user_ids 走 IN 查询
        #   3) 回写 Redis
        # 当前列表场景简单列表页未启用 Redis 缓存（只有 get_user_roles 内部用了），
        # 故直接批量查 DB。
        role_map = await RoleRepository.list_user_role_codes_by_user_ids(db, user_ids)

        return users, total, role_map

    @staticmethod
    async def get_profile(db: AsyncSession, user_id: int) -> Optional[User]:
        """获取用户 ORM 实体"""
        return await UserRepository.get_by_id(db, user_id)

    @staticmethod
    async def get_profile_full(db: AsyncSession, user_id: int) -> "UserProfileVO":
        """获取用户账户信息完整 VO"""
        from src.app.schemas.user import UserProfileVO
        from src.repositories.extra_info_field_repo import ExtraInfoFieldRepository

        user = await UserService.get_profile(db, user_id)
        if not user:
            return None

        field_defs = await ExtraInfoFieldRepository.list_all(db, include_inactive=False)
        extra_info_field_defs = [
            {
                "id": f.id,
                "name": f.name,
                "type": f.type,
                "options": f.options or [],
                "sortOrder": f.sort_order,
            }
            for f in field_defs
        ]

        score_tree: List[dict] = []
        if user.score_info and user.score_info.get("scores"):
            from src.services.score_data_service import ScoreDataService
            roots = await ScoreDataService._load_category_roots(db)
            score_tree = ScoreDataService._build_tree(
                roots,
                user.score_info["scores"],
                include_applications=False,
            )

        return UserProfileVO.from_orm_to_vo(
            user,
            extra_info_field_defs=extra_info_field_defs,
            score_tree=score_tree,
        )

    @staticmethod
    async def update_profile(
        db: AsyncSession,
        user_id: int,
        data: Dict[str, Any],
    ) -> bool:
        """更新用户账户信息"""
        user = await UserRepository.get_by_id(db, user_id)
        if not user:
            return False

        forbidden = {
            "id", "username", "score_info",
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
        user_id: int,
        extra_info: dict,
    ) -> bool:
        """更新用户扩展信息"""
        user = await UserRepository.get_by_id(db, user_id)
        if not user:
            return False

        await UserRepository.update_extra_info(db, user, extra_info)
        return True

    @staticmethod
    async def get_current_user_profile(db: AsyncSession) -> Optional["UserProfileVO"]:
        """获取当前登录用户的账户信息"""
        from src.app.context import get_user_id
        user_id = get_user_id()
        if not user_id:
            return None

        return await UserService.get_profile_full(db, user_id)

    @staticmethod
    async def update_current_user_profile(
        db: AsyncSession,
        data: Dict[str, Any],
    ) -> bool:
        """更新当前登录用户的账户信息"""
        from src.app.context import get_user_id
        user_id = get_user_id()
        if not user_id:
            return False

        return await UserService.update_profile(db, user_id, data)

    @staticmethod
    async def update_current_user_extra_info(
        db: AsyncSession,
        extra_info: dict,
    ) -> bool:
        """更新当前登录用户的扩展信息"""
        from src.app.context import get_user_id
        user_id = get_user_id()
        if not user_id:
            return False

        return await UserService.update_extra_info(db, user_id, extra_info)

    @staticmethod
    async def get_user_roles(
        db: AsyncSession,
        user_id: int,
    ) -> List[int]:
        """获取用户角色 ID 列表"""
        return await RoleRepository.get_user_role_ids(db, user_id)

    @staticmethod
    async def assign_user_roles(
        db: AsyncSession,
        user_id: int,
        role_ids: List[int],
    ) -> None:
        """分配用户角色"""
        await UserRepository.assign_roles(db, user_id, role_ids)
        await UserService.clear_user_cache(user_id)

    @staticmethod
    async def get_current_user_full_info(db: AsyncSession) -> "CurrentUserInfoVO":
        """获取当前登录用户的完整信息"""
        from src.app.context import get_user_id, get_user_roles, get_user_permissions
        from src.app.schemas.user import CurrentUserInfoVO

        user_id = get_user_id()
        if not user_id:
            raise NotFoundError("用户未登录")

        user = await UserService.get_user_by_id_or_raise(db, user_id)
        return CurrentUserInfoVO.from_orm_to_vo(
            user,
            roles=get_user_roles(),
            permissions=get_user_permissions(),
        )

    @staticmethod
    async def delete_user_with_raise(
        db: AsyncSession,
        user_id: int,
    ) -> None:
        """删除用户（用户不存在时抛 NotFoundError）"""
        user = await UserRepository.get_by_id(db, user_id)
        if not user:
            raise NotFoundError(f"用户不存在: id={user_id}")

        await db.delete(user)
        await UserService.clear_user_cache(user_id)

    # =========================================================================
    # 缓存清理
    # =========================================================================

    @staticmethod
    async def clear_user_cache(user_id: int):
        """清除用户缓存"""
        redis = await get_redis()
        keys = [
            f"rbac:user:roles:{user_id}",
            f"rbac:user:perms:{user_id}",
            f"status:user:{user_id}",
            f"rbac:user:full:{user_id}",
        ]
        await redis.delete(*keys)

    @staticmethod
    async def clear_user_status_cache(user_id: int):
        """清除用户状态缓存"""
        redis = await get_redis()
        await redis.delete(f"status:user:{user_id}")
