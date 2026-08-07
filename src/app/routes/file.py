from typing import Annotated
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Form, Query, UploadFile
from fastapi import HTTPException, status
from fastapi.responses import Response

from src.app.dependencies import get_file_service, get_storage
from src.app import response as R
from src.infra.storage import Storage
from src.app.schemas import (
    FileUploadRequest,
    FileAvatarUploadRequest,
    FileUpdateRequest,
    FileDeleteRequest,
    FileQueryRequest,
    FileVO,
    FileDataVO,
)
from src.services.file_service import FileService
from src.exceptions import UnsupportedMediaTypeError

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
        originalName=file.filename or "avatar",
    )
    _, url = await service.upload_avatar(req)
    return R.success_resp(url, msg="头像上传成功")


# ============ 1.5 富文本专用：不写 file_metadata，独立通道 ============

def _make_editor_object_name(filename: str | None) -> str:
    """生成 editor/temp/{uuid}.{ext} 形式的 object key。

    - 固定 editor/temp/ 前缀：临时文件，保存时迁移到最终路径
    - 后缀从原文件名提取并截断到 10 字符（避免超长扩展名被恶意利用）
    - 兜底无扩展名时只保留 uuid
    """
    ext = Path(filename or "img").suffix.lstrip(".").lower()[:10]
    if ext and all(c.isalnum() or c in "._-" for c in ext):
        return f"editor/temp/{uuid4().hex}.{ext}"
    return f"editor/temp/{uuid4().hex}"


@router.post("/editor/upload", status_code=201)
async def upload_editor_image(
    content: bytes = Depends(_read_and_validate_size),
    file: UploadFile = File(..., description="富文本图片"),
    storage: Storage = Depends(get_storage),
):
    """富文本图片上传：直接存 MinIO editor/temp/，不写 file_metadata。

    - 固定 editor/temp/ 前缀的 key
    - 返回签名 URL，前端直接存储在 HTML 中
    """
    key = _make_editor_object_name(file.filename)
    content_type = file.content_type or "application/octet-stream"

    await storage.upload(
        file_obj=BytesIO(content),
        key=key,
        content_type=content_type,
    )
    url = storage.get_presigned_download_url(
        key,
        original_name=None,
        expiry=3600,
        as_attachment=False,
    )
    return R.created_resp(
        {"objectName": key, "url": url},
        msg="富文本图片上传成功",
    )


# ============ 2. 查询 ============

@router.get("/search")
async def search_files(
    req: Annotated[FileQueryRequest, Query()],
    service: FileService = Depends(get_file_service),
):
    """文件分页搜索——DTO 自动解析（§5.3）"""
    page = await service.search_files(req)
    return R.query_resp(page.model_dump())


# ============ 3. 预览 / 下载（v8.0 统一接口）============


@router.get("/preview")
async def get_preview(
    id: int = Query(..., ge=1),
    service: FileService = Depends(get_file_service),
):
    """直接预览文件——支持 PDF、图片、Word(docx)"""
    try:
        meta, data = await service.get_preview_for_inline(id)
    except UnsupportedMediaTypeError:
        return R.success_resp({"unsupported": True})

    content_type = meta.contentType or "application/octet-stream"
    encoded_name = quote(meta.originalName, safe="")
    disposition = f"inline; filename*=UTF-8''{encoded_name}"
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/download-url")
async def get_download_url(
    id: int = Query(..., ge=1),
    expiryMinutes: int = Query(
        60,
        ge=1,
        le=1440,
        description="URL 过期分钟数（默认 60min，最大 24h）",
    ),
    service: FileService = Depends(get_file_service),
):
    vo = await service.get_download_data(id, expiryMinutes)
    return R.query_resp(vo.model_dump())


# ============ 4. 更新 / 删除 ============

@router.post("/update")
async def update_file(
    req: FileUpdateRequest,
    service: FileService = Depends(get_file_service),
):
    """更新文件元信息（仅支持更新 originalName）"""
    vo = await service.update_file(req, req.id)
    return R.success_resp(vo.model_dump(), msg="文件信息已更新")


@router.post("/delete")
async def delete_file(
    req: FileDeleteRequest,
    service: FileService = Depends(get_file_service),
):
    """软删除文件"""
    await service.delete_file(req.id)
    return R.success_resp(msg="删除成功")
