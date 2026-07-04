"""文件路由

路由职责（唯一）：
    1. 接收 HTTP 请求（FastAPI 自动解析 Query / Path / File）
    2. 调 FileService
    3. 把 service 返回值包成统一 JSONResponse

业务异常（FileNotFoundError / FileForbiddenError / FileAuthError）
由 main.py 全局 exception_handler 自动映射为 HTTP 响应 —— 路由不写 try/except。
文件大小校验（413）由 FastAPI Depends 在参数解析阶段拦截 —— 路由不写校验。
"""
import io
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse

from src.app.context import get_user_id, get_user_permissions
from src.app.dependencies import get_file_service
from src.app import response as R
from src.app.schemas import (
    FileInfoVO,
    FileMetadataVO,
    FileUpdateRequest,
    FileUpdateResponse,
)
from src.services.file_service import FileService

router = APIRouter(prefix="/api/file", tags=["文件"])


# ============ 路由辅助：HTTP 层文件大小校验 ============
# 这是路由职责：把 HTTP 协议对象（UploadFile）解出 bytes 并校验体积。
# 用 FastAPI Depends 注入，调用方无需感知。

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


# ============ 路由辅助：把 ORM 列表转 VO 列表 ============
# 这是路由职责：service 返回 ORM，路由负责序列化为响应 DTO

def _to_metadata_vo_list(files):
    return [FileMetadataVO.from_orm_obj(f).model_dump() for f in files]


def _streaming_response(file_data: bytes, content_type: str, original_name: str):
    """文件下载流（Content-Disposition 由 HTTP 协议层决定）"""
    encoded_name = quote(original_name, safe='')
    return StreamingResponse(
        io.BytesIO(file_data),
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
        },
    )


# ============ 1. 上传 ============

@router.post("/upload")
async def upload_file(
    content: bytes = Depends(_read_and_validate_size),
    file: UploadFile = File(..., description="上传文件"),
    fileCategory: str = Query("PROOF"),
    filePurpose: str = Query("加分证明材料"),
    service: FileService = Depends(get_file_service),
):
    """通用文件上传"""
    file_meta, url = await service.upload_file(
        file_data=content,
        original_name=file.filename or "unnamed",
        content_type=file.content_type or "application/octet-stream",
        user_id=get_user_id(),
        category=fileCategory,
        purpose=filePurpose,
    )
    return R.success_resp({
        "fileId": file_meta.id,
        "originalName": file_meta.original_name,
        "url": url,
    })


@router.post("/avatar")
async def upload_avatar(
    content: bytes = Depends(_read_and_validate_size),
    file: UploadFile = File(..., description="头像文件"),
    service: FileService = Depends(get_file_service),
):
    """上传头像（返回公开直链 URL）"""
    _, url = await service.upload_avatar(
        file_data=content,
        user_id=get_user_id(),
        content_type=file.content_type or "image/jpeg",
    )
    return R.success_resp(url)


# ============ 2. 预览 URL ============

@router.get("/{file_id}/preview")
async def get_preview_url(
    file_id: int,
    expiryMinutes: int = Query(60),
    service: FileService = Depends(get_file_service),
):
    """按 fileId 拿预览 URL（带鉴权，鉴权失败由全局 handler 自动 403/404）"""
    url = await service.get_preview_url(
        file_id,
        user_id=get_user_id(),
        user_permissions=get_user_permissions(),
    )
    return R.success_resp(url)


@router.get("/preview-by-name")
async def get_preview_url_by_name(
    objectName: str = Query(..., description="S3 对象 key"),
    expiryMinutes: int = Query(60, ge=1, le=1440),
    service: FileService = Depends(get_file_service),
):
    """按 S3 object_name 直接拿预览 URL（仅要求登录）"""
    url = service.get_access_url_by_key(objectName, expiry=expiryMinutes * 60)
    return R.success_resp(url)


# ============ 3. 搜索 ============

@router.get("/search")
async def search_files(
    fileName: Optional[str] = Query(None, description="文件名模糊查询"),
    fileCategory: Optional[str] = Query(None, description="文件分类"),
    uploadUserId: Optional[int] = Query(None, description="上传用户ID"),
    startTime: Optional[str] = Query(None, description="开始时间（ISO8601）"),
    endTime: Optional[str] = Query(None, description="结束时间（ISO8601）"),
    pageNum: int = Query(1, ge=1, description="页码"),
    pageSize: int = Query(20, ge=1, le=100, description="每页大小"),
    service: FileService = Depends(get_file_service),
):
    """文件分页搜索"""
    from datetime import datetime as _dt
    start_dt = _dt.fromisoformat(startTime) if startTime else None
    end_dt = _dt.fromisoformat(endTime) if endTime else None

    files, total = await service.search_files(
        user_id=uploadUserId,
        category=fileCategory,
        filename_keyword=fileName,
        start_time=start_dt,
        end_time=end_dt,
        page=pageNum,
        size=pageSize,
    )

    return R.success_resp({
        "list": _to_metadata_vo_list(files),
        "total": total,
        "pageNum": pageNum,
        "pageSize": pageSize,
        "pages": (total + pageSize - 1) // pageSize if total > 0 else 0,
    })


# ============ 4. 下载 ============

@router.get("/download/{file_id}")
async def download_file_by_prefix(
    file_id: int,
    service: FileService = Depends(get_file_service),
):
    """下载（路径前缀形式：/api/file/download/{fileId}）"""
    file_data, content_type, original_name = await service.get_download_stream(
        file_id,
        user_id=get_user_id(),
        user_permissions=get_user_permissions(),
    )
    return _streaming_response(file_data, content_type, original_name)


@router.get("/{file_id}/download")
async def download_file_by_suffix(
    file_id: int,
    service: FileService = Depends(get_file_service),
):
    """下载（RESTful 后缀形式：/api/file/{fileId}/download）"""
    file_data, content_type, original_name = await service.get_download_stream(
        file_id,
        user_id=get_user_id(),
        user_permissions=get_user_permissions(),
    )
    return _streaming_response(file_data, content_type, original_name)


# ============ 5. CRUD：查 / 改 / 删 ============

@router.get("/{file_id}")
async def get_file_info(
    file_id: int,
    service: FileService = Depends(get_file_service),
):
    """单个文件元信息"""
    file_meta = await service.get_file_by_id(file_id)
    if not file_meta:
        from src.services.file_service import FileNotFoundError
        raise FileNotFoundError()
    return R.success_resp(FileInfoVO.from_orm_obj(file_meta).model_dump())


@router.put("/{file_id}")
async def update_file(
    file_id: int,
    body: FileUpdateRequest,
    service: FileService = Depends(get_file_service),
):
    """更新文件元信息（重命名 / 改用途）"""
    file_meta = await service.update_file_meta(
        file_id,
        user_id=get_user_id(),
        user_permissions=get_user_permissions(),
        original_name=body.originalName,
        file_purpose=body.filePurpose,
    )
    return R.success_resp(FileUpdateResponse.from_orm_obj(file_meta).model_dump())


@router.delete("/{file_id}")
async def delete_file(
    file_id: int,
    service: FileService = Depends(get_file_service),
):
    """软删除文件（本人 / 超管）"""
    await service.delete_file(
        file_id,
        user_id=get_user_id(),
        user_permissions=get_user_permissions(),
    )
    return R.success_resp(msg="删除成功")


# ============ 6. 占位：证明材料审核（待业务模块化） ============

@router.get("/proof/list/{application_id}")
async def get_proof_list(application_id: int):
    """占位：获取申请的所有证明材料（待证明模块接管）"""
    return R.success_resp({"proofs": []})


@router.post("/proof/{proof_id}/approve")
async def approve_proof(proof_id: int, comment: Optional[str] = Query(None)):
    """占位：审核通过证明材料"""
    return R.success_resp(msg="审核通过")


@router.post("/proof/{proof_id}/reject")
async def reject_proof(proof_id: int, comment: Optional[str] = Query(None)):
    """占位：驳回证明材料"""
    return R.success_resp(msg="已驳回")