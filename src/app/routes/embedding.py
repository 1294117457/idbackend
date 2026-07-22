"""Embedding 管理接口

提供管理端的 embedding 上传、删除、查询等功能。
"""
from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.dependencies import get_db
from src.app import response as R
from src.services.embedding_service import get_embedding_service
from src.app.schemas.embedding import (
    EmbeddingUploadRequest,
    EmbeddingUpdateRequest,
    EmbeddingQueryRequest,
    EmbeddingDeleteRequest,
    EmbeddingSearchRequest,
)

router = APIRouter(prefix="/api/admin/embedding", tags=["Embedding 管理"])


# ═══════════════════════════════════════════════════════════════════════════════
# 上传 / 更新
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/upload")
async def upload_embedding(
    request: EmbeddingUploadRequest,
    db: AsyncSession = Depends(get_db),
):
    """上传并索引新的 embedding。

    - 生成向量并存储到数据库
    - 同一 category + ref_id 组合会执行 upsert（更新）
    """
    service = get_embedding_service()
    result = await service.upload(db, request)
    return R.query_resp(result)


@router.post("/upload-file")
async def upload_file_and_parse(
    file: UploadFile = File(..., description="支持 PDF/DOCX/XLSX/TXT"),
    db: AsyncSession = Depends(get_db),
):
    """上传文件 → 自动解析文本 → 返回解析后的内容（不直接入库）。

    用于：
    - 前端预览解析结果
    - 用户确认后再手动入库
    """
    content = await file.read()
    if not content:
        return R.error_resp("文件内容为空")

    service = get_embedding_service()
    parsed_text = service.parse_file(content, file.filename or "")

    if not parsed_text or not parsed_text.strip():
        return R.error_resp("文件解析失败或内容为空")

    return R.query_resp({
        "filename": file.filename,
        "title": file.filename,
        "content": parsed_text,
        "contentLength": len(parsed_text),
    })


@router.post("/upload-file-and-index")
async def upload_file_and_index(
    file: UploadFile = File(..., description="支持 PDF/DOCX/XLSX/TXT"),
    title: str | None = None,
    category: str = "POLICY",
    db: AsyncSession = Depends(get_db),
):
    """上传文件 → 自动解析 → 直接生成向量并入库（一步到位）。

    - 适用于大文件场景，避免前端把整段文本回填到 JSON body
    - 同一 category + ref_id 组合会执行 upsert
    """
    from src.app.schemas.embedding import EmbeddingUploadRequest

    file_bytes = await file.read()
    if not file_bytes:
        return R.error_resp("文件内容为空")

    service = get_embedding_service()
    parsed_text = service.parse_file(file_bytes, file.filename or "")
    if not parsed_text or not parsed_text.strip():
        return R.error_resp("文件解析失败或内容为空")

    request = EmbeddingUploadRequest(
        title=title or file.filename or "",
        content=parsed_text,
        category=category,
    )
    result = await service.upload(db, request)
    return R.success_resp(result, msg="上传并入库成功")


@router.put("/{embedding_id}")
async def update_embedding(
    embedding_id: int,
    request: EmbeddingUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新 embedding（仅更新文本，向量会重新生成）"""
    service = get_embedding_service()
    result = await service.update(db, embedding_id, request)
    if result is None:
        return R.error_resp("Embedding 不存在", code="NOT_FOUND")
    return R.query_resp(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 删除
# ═══════════════════════════════════════════════════════════════════════════════


@router.delete("/batch")
async def delete_embeddings(
    request: EmbeddingDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量删除 embedding"""
    service = get_embedding_service()
    result = await service.delete(db, request)
    return R.query_resp(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/list")
async def list_embeddings(
    category: str | None = None,
    keyword: str | None = None,
    page_num: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """分页查询 embedding 列表"""
    request = EmbeddingQueryRequest(
        category=category,
        keyword=keyword,
        page_num=page_num,
        page_size=page_size,
    )
    service = get_embedding_service()
    result = await service.list_(db, request)
    return R.query_resp(result)


@router.get("/{embedding_id}")
async def get_embedding_detail(
    embedding_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取 embedding 详情（含向量）"""
    service = get_embedding_service()
    result = await service.get_detail(db, embedding_id)
    if result is None:
        return R.error_resp("Embedding 不存在", code="NOT_FOUND")
    return R.query_resp(result)


@router.get("/stats/overview")
async def get_embedding_stats(
    db: AsyncSession = Depends(get_db),
):
    """获取 embedding 统计信息"""
    service = get_embedding_service()
    result = await service.get_stats(db)
    return R.query_resp(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 搜索
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/search")
async def search_embeddings(
    request: EmbeddingSearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """向量语义搜索 embedding"""
    service = get_embedding_service()
    result = await service.search_(db, request)
    return R.query_resp(result)


__all__ = ["router"]
