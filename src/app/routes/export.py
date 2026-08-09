"""导出接口路由（v1.0）

提供学生数据分层导出功能：
  POST /api/export/student-scores    导出学生成绩表（带层次分组 Excel）

Excel 特性：
  - 多级表头（依据保研类别树结构）
  - 列分组 / 大纲折叠（openpyxl Column Outline）
  - 冻结表头 + 自动筛选
"""
from __future__ import annotations

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.dependencies import get_db
from src.app import response as R
from src.services.export_service import generate_export_excel

router = APIRouter(prefix="/api/export", tags=["导出"])


@router.post("/student-scores")
async def export_student_scores(
    body: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """导出学生成绩表（带层次分组 Excel）

    请求体:
      {
        "basicKeys": ["fullName", "studentId", "major", ...],
        "scoreCategoryIds": [1, 5, 7, ...],
        "extraFieldSpecs": [{"id": 2, "name": "政治面貌"}, ...],
        "filters": {
          "major": "计算机",
          "grade": 3,
          "enrollmentYear": 2023,
          "graduationYear": 2027
        }
      }

    返回:
      Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
      文件名: 学生成绩表_YYYYMMDD.xlsx
    """
    basic_keys: List[str] = body.get("basicKeys", [])
    score_category_ids: List[int] = body.get("scoreCategoryIds", [])
    extra_field_specs: List[Dict[str, Any]] = body.get("extraFieldSpecs", [])
    filters: Dict[str, Any] = body.get("filters", {})
    column_order: Optional[List[Dict[str, str]]] = body.get("columnOrder")

    if not basic_keys and not score_category_ids and not extra_field_specs:
        return R.bad_request_resp("至少需要选择一个导出字段")

    try:
        excel_bytes = await generate_export_excel(
            db,
            basic_keys=basic_keys,
            score_category_ids=score_category_ids,
            extra_field_specs=extra_field_specs,
            filters=filters,
            column_order=column_order,
        )
    except Exception as e:
        return R.server_error_resp(f"导出失败: {str(e)}")

    from datetime import datetime
    filename = f"学生成绩表_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    filename_encoded = filename.encode("utf-8").decode("latin-1")

    return StreamingResponse(
        excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
        },
    )
