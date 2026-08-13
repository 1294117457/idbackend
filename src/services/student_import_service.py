from typing import List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User
from src.repositories.user_repo import UserRepository


class StudentImportService:
    """
    学生数据导入 Service

    负责：
    Excel数据(dict)
    ↓
    User对象
    ↓
    写入数据库
    """

    @staticmethod
    async def import_students(
        db: AsyncSession,
        students: List[Dict[str, Any]],
    ):
        """
        批量导入学生

        students格式：

        [
            {
                "student_id": "33120202201909",
                "name": "张三",
                "grade": 2025,
                "major": "计算机",
                "class_name": "计科1班"
            }
        ]
        """

        created = []
        failed = []

        for student in students:

            try:
                # 必填校验
                if not student.get("student_id"):
                    raise ValueError("缺少学号")

                if not student.get("name"):
                    raise ValueError("缺少姓名")


                # 创建用户对象
                user = User(
                    username=student["student_id"],
                    password="123456",

                    student_id=student["student_id"],
                    full_name=student["name"],

                    grade=student.get("grade"),
                    major=student.get("major"),

                    extra_info={
                        "class_name": student.get("class_name")
                    }
                )


                # 保存数据库
                await UserRepository.insert(
                    db,
                    user
                )


                created.append(
                    student["student_id"]
                )


            except Exception as e:

                failed.append(
                    {
                        "student_id": student.get("student_id"),
                        "reason": str(e)
                    }
                )


        return {
            "created": created,
            "failed": failed
        }