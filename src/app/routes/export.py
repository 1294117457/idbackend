"""学生数据导出路由（v8.1）

路由清单（admin only）：
  POST /api/user/admin/export         导出 Excel（流式响应）

权限：所有 admin 均可调用（无需特殊 permission code）

设计：
- 请求体 ExportUsersRequest（含 columns 树、filters）
- 响应：application/vnd.openxmlformats-officedocument.spreadsheetml.sheet（二进制流）
- Content-Disposition 携带 filename（前端拿到 blob 后直接 download）

详见 docs/docs-backend/导出表格/export-后端实现方案.md
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.dependencies import get_db
from src.app.schemas.export import ExportUsersRequest
from src.services.export_service import ExportService

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/user/admin",
    tags=["用户数据导出"],
)


@router.post(
    "/export",
    summary="导出学生数据（流式响应 xlsx）",
    response_class=StreamingResponse,
)
async def export_students(
    req: ExportUsersRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """导出学生数据为 Excel（管理员用）。

    请求体：
    - fileName: 导出文件名（不含扩展名）
    - columns: 列树（任意深度嵌套）
    - filters: 学生范围过滤条件
    - studentIds / excludedIds: 显式指定 / 排除的学生 ID
    - maxApplicationsPerCategory: 每个 category 最多展开 application 数（默认 5）

    响应：
    - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
    - Content-Disposition: attachment; filename*=UTF-8''<encoded>
    """
    xlsx_bytes, filename = await ExportService.stream_students_xlsx(db, req)

    # RFC 5987 编码（兼容中文文件名）
    encoded_filename = quote(filename)
    content_disposition = f"attachment; filename*=UTF-8''{encoded_filename}"

    logger.info(
        f"导出完成: fileName={filename}, students=?, columns={len(req.columns)}"
    )

    return StreamingResponse(
        iter([xlsx_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": content_disposition,
            "Content-Length": str(len(xlsx_bytes)),
        },
    )


__all__ = ["router"]
