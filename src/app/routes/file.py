from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi import HTTPException, status
from fastapi.responses import Response

from src.app.dependencies import get_file_service
from src.app import response as R
from src.app.schemas import (
    FileUploadRequest,
    FileAvatarUploadRequest,
    FileUpdateRequest,
    FileQueryRequest,
    FileVO,
    FileDataVO,
)
from src.services.file_service import FileService

router = APIRouter(prefix="/api/file", tags=["文件"])


# ---------- 内部工具（仅与 HTTP 协议相关：大小校验） ----------

async def _read_and_validate_size(file: UploadFile = File(...)) -> bytes:
    """读取上传文件并校验大小 → 超过限制抛 HTTP 413"""
    from src.infra.config import get_settings

    settings = get_settings()
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件大小不能超过 {settings.MAX_FILE_SIZE // (1024*1024)}MB",
        )
    return content


# ============ 1. 上传（v6.0：中转流逻辑不变，返回 url 改为签名 URL）============

@router.post("/upload", status_code=201)
async def upload_file(
    content: bytes = Depends(_read_and_validate_size),
    file: UploadFile = File(..., description="上传文件"),
    fileCategory: str = Form("PROOF"),
    service: FileService = Depends(get_file_service),
):
    req = FileUploadRequest(fileCategory=fileCategory, file=file, content=content)
    meta, url = await service.upload_file(req)
    return R.created_resp({
        "fileId": meta.id,
        "originalName": meta.original_name,
        "url": url,
    }, msg="文件上传成功")


@router.post("/avatar")
async def upload_avatar(
    content: bytes = Depends(_read_and_validate_size),
    file: UploadFile = File(..., description="头像文件"),
    service: FileService = Depends(get_file_service),
):

    req = FileAvatarUploadRequest(
        content=content,
        contentType=file.content_type or "image/jpeg",
    )
    _, url = await service.upload_avatar(req)
    return R.success_resp(url, msg="头像上传成功")


# ============ 2. 查询 ============

@router.get("/search")
async def search_files(
    req: Annotated[FileQueryRequest, Query()],
    service: FileService = Depends(get_file_service),
):
    """文件分页搜索——DTO 自动解析（§5.3）"""
    page = await service.search_files(req)
    return R.query_resp(page.model_dump())


@router.get("/{file_id}")
async def get_file_info(
    file_id: int,
    service: FileService = Depends(get_file_service),
):
    """单个文件元信息（service 层抛异常，路由层不再判空）"""
    meta = await service.get_file(file_id)
    return R.query_resp(FileVO.from_orm_to_vo(meta).model_dump())


# ============ 3. 预览 / 下载（v6.0 全签名模式）============

@router.get("/{file_id}/preview-url")
async def get_preview_url(
    file_id: int,
    expiryMinutes: int = Query(
        60,
        ge=1,
        le=1440,
        description="URL 过期分钟数（默认 60min，最大 24h）",
    ),
    service: FileService = Depends(get_file_service),
):

    meta, url = await service.get_preview_data(file_id, expiryMinutes)
    return R.query_resp(FileDataVO.from_orm_to_vo(meta, url).model_dump())


@router.get("/{file_id}/preview")
async def get_preview(
    file_id: int,
    service: FileService = Depends(get_file_service),
):
    """直接预览图片/文件——从 MinIO 拉取流经网关返回

    - 前端直接请求，无需签名，降低前端复杂度
    - 响应 5MB 以上大文件可能导致网关超时，建议前端改用预览签名 URL
    """
    meta, data = await service.get_preview_bytes(file_id)
    encoded_name = quote(meta.original_name, safe="")
    disposition = f"inline; filename*=UTF-8''{encoded_name}"
    return Response(
        content=data,
        media_type=meta.content_type,
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/{file_id}/download-url")
async def get_download_url(
    file_id: int,
    expiryMinutes: int = Query(
        60,
        ge=1,
        le=1440,
        description="URL 过期分钟数（默认 60min，最大 24h）",
    ),
    service: FileService = Depends(get_file_service),
):
    meta, url = await service.get_download_data(file_id, expiryMinutes)
    return R.query_resp(FileDataVO.from_orm_to_vo(meta, url).model_dump())


# ============ 4. 更新 / 删除 ============

@router.put("/{file_id}")
async def update_file(
    file_id: int,
    req: FileUpdateRequest,
    service: FileService = Depends(get_file_service),
):
    """更新文件元信息（仅支持更新 originalName）"""
    meta = await service.update_file(req, file_id)
    return R.success_resp(FileVO.from_orm_to_vo(meta).model_dump(), msg="文件信息已更新")


@router.delete("/{file_id}")
async def delete_file(
    file_id: int,
    service: FileService = Depends(get_file_service),
):
    """软删除文件"""
    await service.delete_file(file_id)
    return R.success_resp(msg="删除成功")
