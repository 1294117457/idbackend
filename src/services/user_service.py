"""用户服务"""

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Dict, Any, Tuple
import json
import secrets
import string

from src.models import User, Role, Permission, Application
from src.models.user import UserRole, RolePermission, UserStatus
from src.infra.jwt import hash_password
from src.infra.database import AsyncSessionLocal
from src.infra.redis import get_redis
from src.services.rbac_service import RbacService
from src.app.schemas.errors import NotFoundError, ConflictError


def generate_password(length: int = 12) -> str:
    """生成随机密码"""
    return "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(length)
    )


class UserService:
    @staticmethod
    async def verify_account_active(user_id: int) -> bool:
        redis = await get_redis()
        cache_key = f"{RbacService.USER_STATUS_KEY}{user_id}"
        cached = await redis.get(cache_key)
        if cached is not None:
            return cached == "1"

        async with AsyncSessionLocal() as db:
            user = await db.get(User, user_id)
            is_active = user is not None and user.status == UserStatus.ACTIVE.value

        # 回填缓存（无论 True/False 都缓存，避免穿透攻击时反复打 DB）
        await redis.setex(cache_key, RbacService.CACHE_TTL, "1" if is_active else "0")
        return is_active

    @staticmethod
    async def load_user_rbac(user_id: int) -> Optional[Dict[str, Any]]:
        redis = await get_redis()
        cache_key = f"rbac:user:full:{user_id}"
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)

        async with AsyncSessionLocal() as db:
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

            payload = {
                "user_id": user.id,
                "username": user.username,
                "is_admin": False,
                "roles": list(role_map.values()),
                "permissions": sorted(perm_set),
            }

        await redis.setex(cache_key, RbacService.CACHE_TTL, json.dumps(payload, ensure_ascii=False))
        return payload

    @staticmethod
    async def load_user_auth_info(user_id: int) -> Optional[Dict[str, Any]]:
        if not await UserService.verify_account_active(user_id):
            return None  # 账号被禁用 → 触发旧 401（兼容路径）

        result = await UserService.load_user_rbac(user_id)
        if result is None:
            # 用户不存在（旧行为：返回空角色字典）
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
        if not modified:
            return user
        return user

    @staticmethod
    async def get_user_scores(
        db: AsyncSession,
        user_id: int,
    ) -> dict:
        """获取用户积分（从 score_info 读取，v4.6 适配）

        v4.6 适配：score_info 持久化字段从 categories 字典改为 scores 字典
          - 旧结构: { categories: { cat_id: { name, score, max } }, total, calculated_at }
          - 新结构: { scores: { cat_id: { score, raw } }, total, calculated_at }
          - 此方法返回的 categories 改为从 scores 现算（含 name 从 template_category 拼）

        如果 score_info 为空，返回空结构。
        """
        user = await UserService.get_user_by_id(db, user_id)
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
        await RbacService.clear_user_cache(user_id)
        return True

    @staticmethod
    async def update_user_status(
        db: AsyncSession,
        user_id: int,
        status: str,
    ) -> User:
        """更新用户状态"""
        user = await UserService.get_user_by_id_or_raise(db, user_id)
        user.status = status
        await RbacService.clear_user_status_cache(user_id)
        return user

    @staticmethod
    async def create_user_with_password_gen(
        db: AsyncSession,
        username: str,
        password: Optional[str] = None,
        role_code: Optional[str] = None,
    ) -> Tuple[User, str]:
        """创建用户（可选自动生成密码），返回 (User, raw_password)

        - 若 password 为 None，则自动生成 12 位随机密码
        - 若 role_code 不为空，自动分配该角色
        - 返回原始密码（未加密），供接口返回给前端
        """
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
        """批量创建用户，返回 (created, failed)

        - 自动生成 12 位随机密码
        - 返回 created: [{"username": str, "password": str}]
        - 返回 failed: [{"username": str, "reason": str}]
        """
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
        """获取用户列表（含角色），返回 (users, total, user_roles_map)

        - users: ORM 实体列表
        - total: 总数
        - user_roles_map: {user_id: [role_name, ...]}
        """
        users, total = await UserService.list_users(db, req)

        user_roles_map: Dict[int, List[str]] = {}
        for user in users:
            roles = await RbacService.get_user_roles(db, user.id)
            user_roles_map[user.id] = roles

        return users, total, user_roles_map

    @staticmethod
    async def get_profile(db: AsyncSession, user_id: int) -> Optional[User]:
        """获取用户 ORM 实体（找不到返回 None）

        返回 ORM 实体，由 schema 层的 UserProfileVO.from_orm_to_vo() 转换。
        额外数据（extra_info_field_defs, score_tree）通过参数传入转换方法。
        """
        return await db.get(User, user_id)

    @staticmethod
    async def get_profile_full(db: AsyncSession, user_id: int) -> "UserProfileVO":
        """获取用户账户信息完整 VO

        内部完成 ORM → VO 转换，extra_info_field_defs 和 score_tree 在 service 层计算。
        """
        from src.app.schemas.user import UserProfileVO

        user = await UserService.get_profile(db, user_id)
        if not user:
            return None

        # 获取已启用的字段定义
        from src.repositories.extra_info_field_repo import ExtraInfoFieldRepository
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

        # 计算 score_tree
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
        """更新用户账户信息

        - 过滤不可修改字段
        - 只更新允许的字段
        - 返回是否有修改
        """
        user = await db.get(User, user_id)
        if not user:
            return False

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

        return modified

    @staticmethod
    async def update_extra_info(
        db: AsyncSession,
        user_id: int,
        extra_info: dict,
    ) -> bool:
        """更新用户扩展信息（extra_info）

        合并：保留旧值，更新传入的 key。
        """
        user = await db.get(User, user_id)
        if not user:
            return False

        current = dict(user.extra_info or {})
        current.update(extra_info)
        user.extra_info = current

        return True

    @staticmethod
    async def get_current_user_profile(db: AsyncSession) -> Optional["UserProfileVO"]:
        """获取当前登录用户的账户信息（从 contextvar 获取 user_id）

        返回 UserProfileVO，包含 extra_info_field_defs 和 score_info（含 tree）。
        """
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
        """更新当前登录用户的账户信息（从 contextvar 获取 user_id）"""
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
        """更新当前登录用户的扩展信息（从 contextvar 获取 user_id）"""
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
        return await RbacService.get_user_role_ids(db, user_id)

    @staticmethod
    async def assign_user_roles(
        db: AsyncSession,
        user_id: int,
        role_ids: List[int],
    ) -> None:
        """分配用户角色"""
        await RbacService.assign_roles_to_user(db, user_id, role_ids)

    @staticmethod
    async def get_current_user_full_info(db: AsyncSession) -> "CurrentUserInfoVO":
        """获取当前登录用户的完整信息（从 contextvar 获取 roles/permissions）

        ORM → VO 转换在 schema 层完成。
        """
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
        user = await UserService.get_user_by_id(db, user_id)
        if not user:
            raise NotFoundError(f"用户不存在: id={user_id}")

        await db.delete(user)
        await RbacService.clear_user_cache(user_id)