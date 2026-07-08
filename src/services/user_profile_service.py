"""用户账户信息服务

提供学生端账户信息的获取和更新接口。
"""
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Dict, Any

from src.models import User


class UserProfileService:
    """用户账户信息服务"""

    @staticmethod
    async def get_profile(db: AsyncSession, user_id: int) -> Dict[str, Any]:
        """获取用户账户信息

        - 从 users 表读取基本信息
        - student_id 从 username 提取
        """
        user = await db.get(User, user_id)
        if not user:
            return None

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
