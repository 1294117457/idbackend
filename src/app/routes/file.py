import io
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse

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


# ---------- 内部工具（仅与 HTTP 协议相关：流式响应 + 大小校验） ----------

async def _read_and_validate_size(file: UploadFile = File(...)) -> bytes:
    """读取上传文件并校验大小 → 超过限制抛 HTTP 413"""
    from src.infra.config import get_settings
    from fastapi import HTTPException, status

    settings = get_settings()
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件大小不能超过 {settings.MAX_FILE_SIZE // (1024*1024)}MB",
        )
    return content


def _streaming_response(file_data: bytes, content_type: str, original_name: str):
    encoded_name = quote(original_name, safe='')
    return StreamingResponse(
        io.BytesIO(file_data),
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
        },
    )


# ============ 1. 上传 ============

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
    })


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
    return R.success_resp(url)


# ============ 2. 查询 ============

@router.get("/search")
async def search_files(
    req: Annotated[FileQueryRequest, Query()],
    service: FileService = Depends(get_file_service),
):
    """文件分页搜索——DTO 自动解析（§5.3）"""
    page = await service.search_files(req)
    return R.success_resp(page.model_dump())


@router.get("/{file_id}")
async def get_file_info(
    file_id: int,
    service: FileService = Depends(get_file_service),
):
    """单个文件元信息（service 层抛异常，路由层不再判空）"""
    meta = await service.get_file(file_id)
    return R.success_resp(FileVO.from_orm_obj(meta).model_dump())


# ============ 3. 预览 / 下载 ============

@router.get("/{file_id}/preview")
async def get_preview_url(
    file_id: int,
    expiryMinutes: int = Query(
        60,
        ge=1,
        le=1440,
        description="URL 过期分钟数（仅 POLICY/PROOF 生效；AVATAR 公开直链无过期）",
    ),
    service: FileService = Depends(get_file_service),
):

    meta, url = await service.get_preview_data(file_id, expiryMinutes)
    return R.success_resp(FileDataVO.from_orm_obj(meta, url).model_dump())


@router.get("/{file_id}/download")
async def download_file(
    file_id: int,
    service: FileService = Depends(get_file_service),
):
    """下载文件（流式响应）"""
    file_data, content_type, original_name = await service.get_download_stream(file_id)
    return _streaming_response(file_data, content_type, original_name)


# ============ 4. 更新 / 删除 ============

@router.put("/{file_id}")
async def update_file(
    file_id: int,
    req: FileUpdateRequest,
    service: FileService = Depends(get_file_service),
):
    """更新文件元信息（仅支持更新 originalName）"""
    meta = await service.update_file(req, file_id)
    return R.success_resp(FileVO.from_orm_obj(meta).model_dump())


@router.delete("/{file_id}")
async def delete_file(
    file_id: int,
    service: FileService = Depends(get_file_service),
):
    """软删除文件"""
    await service.delete_file(file_id)
    return R.success_resp(msg="删除成功")