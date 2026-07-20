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
    FileQueryRequest,
    FileVO,
    FileDataVO,
)
from src.services.file_service import FileService
from src.services.office_converter import OfficeConvertError

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


# ============ 1.5 富文本专用：不写 file_metadata，独立通道 ============

def _make_editor_object_name(filename: str | None) -> str:
    """生成 editor/{uuid}.{ext} 形式的 object key。

    - 强制 editor/ 前缀：让 RichTextImageProcessor 的安全过滤直接命中
    - 后缀从原文件名提取并截断到 10 字符（避免超长扩展名被恶意利用）
    - 兜底无扩展名时只保留 uuid
    """
    ext = Path(filename or "img").suffix.lstrip(".").lower()[:10]
    if ext and all(c.isalnum() or c in "._-" for c in ext):
        return f"editor/{uuid4().hex}.{ext}"
    return f"editor/{uuid4().hex}"


@router.post("/editor/upload", status_code=201)
async def upload_editor_image(
    content: bytes = Depends(_read_and_validate_size),
    file: UploadFile = File(..., description="富文本图片"),
    storage: Storage = Depends(get_storage),
):
    """富文本图片上传：直接存 MinIO，不写 file_metadata。

    与 /upload 的区别：
    - 走 storage 抽象层，不进 file_service（避免写 file_metadata 表）
    - 固定 editor/ 前缀的 key
    - 返回 objectName + 1 小时签名 URL

    前端使用：
    - 上传成功拿 objectName 拼占位 src="editor://object/{objectName}"
    - 编辑期 / 渲染期通过 /editor/sign-urls 拿签名 URL
    """
    key = _make_editor_object_name(file.filename)
    content_type = file.content_type or "application/octet-stream"

    await storage.upload(
        file_obj=BytesIO(content),
        key=key,
        content_type=content_type,
    )
    url = storage.get_download_url(
        key,
        original_name=None,
        expiry=3600,
        force_attachment=False,
    )
    return R.created_resp(
        {"objectName": key, "url": url},
        msg="富文本图片上传成功",
    )


@router.post("/editor/sign-urls")
async def sign_editor_urls(
    keys: list[str] = Body(..., embed=True, description="object key 列表（去重）"),
    expiryMinutes: int = Query(
        60,
        ge=1,
        le=1440,
        description="URL 过期分钟数（默认 60min，最大 24h）",
    ),
    storage: Storage = Depends(get_storage),
):
    """富文本占位渲染专用：按 object key 批量签 URL，**不查 DB**。

    - 仅允许 editor/ 前缀（防滥用签其它类别的对象）
    - 不存在的 key 不会出现在返回 map 里（前端静默降级，破图占位由后端 _do_replace 兜底）
    """
    safe_keys: set[str] = set()
    for k in keys:
        if not isinstance(k, str) or not k.startswith("editor/"):
            continue
        # editor/ 后面必须有内容（防裸 "editor/"）
        if len(k) <= len("editor/"):
            continue
        safe_keys.add(k)
    if not safe_keys:
        return R.success_resp({})

    url_map = {
        k: storage.get_download_url(
            k,
            original_name=None,
            expiry=expiryMinutes * 60,
            force_attachment=False,
        )
        for k in safe_keys
    }
    return R.success_resp(url_map, msg="ok")


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


@router.get("/{file_id}/preview")
async def get_preview(
    file_id: int,
    service: FileService = Depends(get_file_service),
):
    """直接预览文件——从 MinIO 拉取后返回（Office 文件自动转 PDF）

    行为：
    - 图片/PDF/视频/音频：原样返回原 content-type
    - Office（docx/xlsx/pptx/doc/xls/ppt/odt/ods/odp）：用 LibreOffice headless 转 PDF 后返回
    - 超过大小阈值：413（图片/PDF 5MB、Office 10MB）
    - Office 转换失败 / LibreOffice 未安装：返 501 + 提示下载
    """
    try:
        meta, data, content_type = await service.get_preview_for_inline(file_id)
    except OfficeConvertError as e:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Office 文件预览转换失败，请下载查看：{e!s}",
        )

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
    vo = await service.get_download_data(file_id, expiryMinutes)
    return R.query_resp(vo.model_dump())


# ============ 4. 更新 / 删除 ============

@router.put("/{file_id}")
async def update_file(
    file_id: int,
    req: FileUpdateRequest,
    service: FileService = Depends(get_file_service),
):
    """更新文件元信息（仅支持更新 originalName）"""
    vo = await service.update_file(req, file_id)
    return R.success_resp(vo.model_dump(), msg="文件信息已更新")


@router.delete("/{file_id}")
async def delete_file(
    file_id: int,
    service: FileService = Depends(get_file_service),
):
    """软删除文件"""
    await service.delete_file(file_id)
    return R.success_resp(msg="删除成功")
