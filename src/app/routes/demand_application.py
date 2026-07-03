"""需求申请路由 - 兼容前端"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from src.app.deps import get_db
from src.app.context import get_username
from src.app import response as R
from src.models import DemandApplication

router = APIRouter(prefix="/api/demand-application", tags=["需求申请"])


class DemandApplicationItem(BaseModel):
    templateId: int
    templateName: str
    selectedCondition: Optional[str] = None
    inputValue: str


class DemandApplicationSubmit(BaseModel):
    applications: List[DemandApplicationItem]
    proofFiles: Optional[List[dict]] = None  # [{fileId, fileName}]


class DemandApplicationService:
    """需求申请服务"""

    @staticmethod
    async def get_by_student(db: AsyncSession, student_id: str) -> Optional[DemandApplication]:
        result = await db.execute(
            select(DemandApplication).where(DemandApplication.student_id == student_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(db: AsyncSession) -> List[DemandApplication]:
        result = await db.execute(select(DemandApplication))
        return list(result.scalars().all())

    @staticmethod
    async def upsert(
        db: AsyncSession,
        student_id: str,
        applications: List[dict],
    ) -> DemandApplication:
        existing = await DemandApplicationService.get_by_student(db, student_id)
        if existing:
            existing.application_data = {"applications": applications}
            existing.submit_time = datetime.utcnow()
            await db.commit()
            await db.refresh(existing)
            return existing
        else:
            app = DemandApplication(
                student_id=student_id,
                application_data={"applications": applications},
                submit_time=datetime.utcnow(),
            )
            db.add(app)
            await db.commit()
            await db.refresh(app)
            return app

    @staticmethod
    async def delete_by_student(db: AsyncSession, student_id: str) -> bool:
        app = await DemandApplicationService.get_by_student(db, student_id)
        if not app:
            return False
        await db.delete(app)
        await db.commit()
        return True


@router.post("/submit")
async def submit(
    data: DemandApplicationSubmit,
    db: AsyncSession = Depends(get_db),
):
    """提交需求申请（覆盖式）"""
    applications = [a.model_dump() for a in data.applications]
    await DemandApplicationService.upsert(db, get_username(), applications)
    return R.success_resp(msg="提交成功")


@router.get("/my")
async def get_my(
    db: AsyncSession = Depends(get_db),
):
    """获取我的需求申请"""
    result = await DemandApplicationService.get_by_student(db, get_username())
    if not result:
        return R.success_resp(msg="暂无申请记录")

    apps_data = result.application_data.get("applications", [])
    return R.success_resp({
        "id": result.id,
        "studentId": result.student_id,
        "applications": apps_data,
        "submitTime": str(result.submit_time) if result.submit_time else None,
        "updatedAt": str(result.updated_at) if result.updated_at else None,
    })


@router.delete("/my")
async def delete_my(
    db: AsyncSession = Depends(get_db),
):
    """删除我的需求申请"""
    result = await DemandApplicationService.delete_by_student(db, get_username())
    if not result:
        return R.not_found_resp("暂无申请记录")
    return R.success_resp(msg="删除成功")


@router.get("/all")
async def get_all(
    db: AsyncSession = Depends(get_db),
):
    """获取所有需求申请"""
    results = await DemandApplicationService.get_all(db)
    return R.success_resp([{
        "id": r.id,
        "studentId": r.student_id,
        "applications": r.application_data.get("applications", []),
        "submitTime": str(r.submit_time) if r.submit_time else None,
    } for r in results])
