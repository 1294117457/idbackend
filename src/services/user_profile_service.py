"""用户账户信息服务

提供学生端账户信息的获取和更新接口。
"""
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Dict, Any, List

from src.models import User


class UserProfileService:
    """用户账户信息服务"""

    @staticmethod
    async def get_profile(db: AsyncSession, user_id: int) -> Optional[Dict[str, Any]]:
        """获取用户账户信息

        - 从 users 表读取基本信息
        - student_id 从 username 提取
        - extra_info_field_defs：已启用字段定义（用于前端动态渲染）
        - score_info：v4.6 起精简为 { calculated_at, total, scores }
          * 为了让 profile 页面直接渲染分数树（不再调 /api/score/me），
            本方法在返回时把 tree 字段作为派生数据附加到 score_info 里
          * tree 不写 DB，仅用于接口返回（对齐 /api/score/me 的展示形态）
        """
        user = await db.get(User, user_id)
        if not user:
            return None

        # 一次性查出已启用的字段定义（供前端渲染扩展信息表单）
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

        # v4.6：score_info 拆分为持久化字段（scores/total/calculated_at） + 派生字段（tree）
        score_info = dict(user.score_info or {})
        if score_info.get("scores"):
            from src.services.score_data_service import ScoreDataService
            roots = await ScoreDataService._load_category_roots(db)
            score_info["tree"] = ScoreDataService._build_tree(
                roots,
                score_info["scores"],
                include_applications=False,
            )
        else:
            score_info.setdefault("tree", [])

        return {
            "id": user.id,
            "student_id": User.extract_student_id(user.username),
            "username": user.username,
            "full_name": user.full_name,
            "phone": user.phone,
            "avatar": user.avatar,
            "grade": user.grade,
            "enrollment_year": user.enrollment_year,
            "graduation_year": user.graduation_year,
            "major": user.major,
            "extra_info": user.extra_info or {},
            "score_info": score_info,
            "extra_info_field_defs": extra_info_field_defs,
        }

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

        # 不允许修改的字段
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
            await db.commit()
            await db.refresh(user)

        return modified

    @staticmethod
    async def update_extra_info(
        db: AsyncSession,
        user_id: int,
        extra_info: dict,
    ) -> bool:
        """更新用户扩展信息（extra_info）"""
        user = await db.get(User, user_id)
        if not user:
            return False

        # 合并：保留旧值，更新传入的 key
        current = dict(user.extra_info or {})
        current.update(extra_info)
        user.extra_info = current

        await db.commit()
        await db.refresh(user)
        return True
