from typing import List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.infra.jwt import hash_password
from src.models.user import User, UserStatus
from src.repositories.user_repo import UserRepository


class StudentImportService:
    """学生数据导入 Service"""

    @staticmethod
    def _normalize_gender(value: str | None) -> str | None:
        if value is None:
            return None

        value = value.strip()

        mapping = {
            "男": "M",
            "女": "F",
            "M": "M",
            "F": "F",
            "其他": "OTHER",
            "OTHER": "OTHER",
        }

        return mapping.get(value, value)

    @staticmethod
    async def import_students(
        db: AsyncSession,
        students: List[Dict[str, Any]],
    ) -> Dict[str, List]:

        created: List[str] = []
        failed: List[Dict[str, Any]] = []

        for student in students:
            student_id = student.get("student_id")

            try:
                if not student_id:
                    raise ValueError("缺少学号")

                if not student.get("name"):
                    raise ValueError("缺少姓名")

                username = student_id

                existing = await UserRepository.get_by_username(
                    db,
                    username,
                )

                if existing:
                    failed.append(
                        {
                            "student_id": student_id,
                            "reason": "用户已存在",
                        }
                    )
                    continue

                user = User(
                    username=username,
                    password=hash_password("123456"),
                    status=UserStatus.ACTIVE.value,
                    student_id=student_id,
                    full_name=student.get("name"),
                    department=student.get("department"),
                    major=student.get("major"),
                    gender=StudentImportService._normalize_gender(
                        student.get("gender")
                    ),
                    id_card_number=student.get("id_card_number"),
                    phone=student.get("phone"),
                )

                await UserRepository.insert(db, user)

                created.append(student_id)

            except Exception as e:
                failed.append(
                    {
                        "student_id": student_id,
                        "reason": str(e),
                    }
                )

        return {
            "created": created,
            "failed": failed,
        }