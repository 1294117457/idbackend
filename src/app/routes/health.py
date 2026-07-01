"""健康检查"""
from fastapi import APIRouter

router = APIRouter(tags=["健康"])


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok"}


@router.get("/")
async def root():
    """根路径"""
    return {"message": "ID-AIDemo API", "version": "1.0.0"}
