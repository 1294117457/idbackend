"""文件路由 - 兼容前端"""
from fastapi import APIRouter, Depends, UploadFile, File, Query, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import io

from src.app.deps import get_db, get_current_user, CurrentUser
from src.app.response import success_response, error_response
from src.services import FileService

router = APIRouter(prefix="/api/file", tags=["文件"])


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    fileCategory: str = Query("PROOF"),
    filePurpose: str = Query("加分证明材料"),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """上传文件"""
    content = await file.read()

    # 检查文件大小 (50MB)
    if len(content) > 50 * 1024 * 1024:
        return error_response("文件大小不能超过 50MB", code=400)

    file_meta, url = await FileService.upload_file(
        db=db,
        file_data=content,
        original_name=file.filename,
        content_type=file.content_type or "application/octet-stream",
        user_id=user.user_id,
        category=fileCategory,
        purpose=filePurpose,
    )

    return success_response({
        "fileId": file_meta.id,
        "originalName": file_meta.original_name,
        "url": url,
    })


@router.post("/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """上传头像"""
    content = await file.read()

    file_meta, url = await FileService.upload_avatar(
        db=db,
        file_data=content,
        user_id=user.user_id,
        content_type=file.content_type or "image/jpeg",
    )

    return success_response(url)


@router.get("/{file_id}/preview")
async def get_preview_url(
    file_id: int,
    expiryMinutes: int = Query(60),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取预览URL"""
    url = await FileService.get_preview_url(db, file_id)
    if not url:
        return error_response("文件不存在", code=404)
    return success_response(url)


@router.get("/search")
async def search_files(
    fileName: str = Query(None, description="文件名模糊查询"),
    fileCategory: str = Query(None, description="文件分类"),
    uploadUserId: int = Query(None, description="上传用户ID"),
    startTime: str = Query(None, description="开始时间"),
    endTime: str = Query(None, description="结束时间"),
    pageNum: int = Query(1, ge=1, description="页码"),
    pageSize: int = Query(20, ge=1, le=100, description="每页大小"),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """搜索文件列表(分页)"""
    files, total = await FileService.search_files(
        db=db,
        user_id=uploadUserId,
        category=fileCategory,
        filename_keyword=fileName,
        page=pageNum,
        size=pageSize,
    )

    def format_size(size: int) -> str:
        if size < 1024:
            return f"{size}B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f}KB"
        else:
            return f"{size / (1024 * 1024):.1f}MB"

    return success_response({
        "list": [
            {
                "id": f.id,
                "originalName": f.original_name,
                "fileSize": f.file_size,
                "fileSizeFormatted": format_size(f.file_size),
                "contentType": f.content_type,
                "fileExtension": f.file_extension,
                "fileCategory": f.file_category,
                "filePurpose": f.file_purpose,
                "uploadUserId": f.upload_user_id,
                "uploadTime": str(f.created_at),
            }
            for f in files
        ],
        "total": total,
        "pageNum": pageNum,
        "pageSize": pageSize,
        "pages": (total + pageSize - 1) // pageSize if total > 0 else 0,
    })


@router.get("/download/{file_id}")
async def download_file_legacy(
    file_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """下载文件 (兼容 /download/{fileId} 格式)"""
    result = await FileService.download_file(db, file_id)
    if not result:
        return error_response("文件不存在", code=404)

    file_data, content_type = result
    return StreamingResponse(
        io.BytesIO(file_data),
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename=file"
        }
    )


@router.get("/{file_id}/download")
async def download_file(
    file_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """下载文件"""
    result = await FileService.download_file(db, file_id)
    if not result:
        return error_response("文件不存在", code=404)

    file_data, content_type = result
    return StreamingResponse(
        io.BytesIO(file_data),
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename=file"
        }
    )


@router.get("/{file_id}")
async def get_file_info(
    file_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取文件信息"""
    file_meta = await FileService.get_file_by_id(db, file_id)
    if not file_meta:
        return error_response("文件不存在", code=404)

    return success_response({
        "fileId": file_meta.id,
        "originalName": file_meta.original_name,
        "fileSize": file_meta.file_size,
        "contentType": file_meta.content_type,
        "uploadTime": str(file_meta.created_at),
    })


@router.delete("/{file_id}")
async def delete_file(
    file_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除文件"""
    result = await FileService.delete_file(db, file_id, user.user_id)
    if not result:
        return error_response("文件不存在或无权删除", code=400)
    return success_response(msg="删除成功")


# ========== 证明材料相关 ==========

@router.get("/proof/list/{application_id}")
async def get_proof_list(
    application_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取申请的所有证明材料"""
    # TODO: 实现
    return success_response({"proofs": []})


@router.post("/proof/{proof_id}/approve")
async def approve_proof(
    proof_id: int,
    comment: Optional[str] = Query(None),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """审核通过证明材料"""
    # TODO: 实现
    return success_response(msg="审核通过")


@router.post("/proof/{proof_id}/reject")
async def reject_proof(
    proof_id: int,
    comment: Optional[str] = Query(None),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """驳回证明材料"""
    # TODO: 实现
    return success_response(msg="已驳回")
