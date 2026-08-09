"""学生数据导出服务（v1.0）

使用 openpyxl 生成带层次分组（Column Grouping / Outline）的 Excel 文件。
支持：
  - 多级表头（根据 TemplateCategory 树结构生成合并表头）
  - 列分组/大纲折叠（按分类层级设置 Excel Outline Level）
  - 基础信息列 + 评分分类列 + 扩展信息列

设计决策：
  - 后端生成 Excel（openpyxl 支持完整的 Outline/Grouping 功能）
  - 前端 xlsx (SheetJS CE) 不支持列分组，因此将导出逻辑迁移到后端
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Dict, Any, List

from openpyxl import Workbook
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side, numbers
)
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import User, TemplateCategory


# ════════════════════════════════════════════════════════════════════════
# 样式常量
# ════════════════════════════════════════════════════════════════════════

HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_FONT = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
SUBHEADER_FILL = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
SUBHEADER_FONT = Font(name="微软雅黑", size=10, bold=True, color="1F4E79")
LEAF_HEADER_FILL = PatternFill(start_color="E9EFF7", end_color="E9EFF7", fill_type="solid")
LEAF_HEADER_FONT = Font(name="微软雅黑", size=10, bold=True, color="2D5A8E")
DATA_FONT = Font(name="微软雅黑", size=10)
THIN_BORDER = Border(
    left=Side(style="thin", color="B4C6E7"),
    right=Side(style="thin", color="B4C6E7"),
    top=Side(style="thin", color="B4C6E7"),
    bottom=Side(style="thin", color="B4C6E7"),
)
CENTER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT_ALIGN = Alignment(horizontal="left", vertical="center", wrap_text=True)

# 评分列默认宽度
SCORE_COL_WIDTH = 12
# 基础信息列默认宽度
BASIC_COL_WIDTH = 14


# ════════════════════════════════════════════════════════════════════════
# 列定义工具
# ════════════════════════════════════════════════════════════════════════

BASIC_FIELD_DEFS: Dict[str, Dict[str, Any]] = {
    "fullName":       {"label": "姓名", "width": 10},
    "studentId":      {"label": "学号", "width": 16},
    "major":          {"label": "专业", "width": 16},
    "grade":          {"label": "年级", "width": 8},
    "enrollmentYear": {"label": "入学年份", "width": 10},
    "graduationYear": {"label": "毕业年份", "width": 10},
    "phone":          {"label": "手机号", "width": 14},
}

GRADE_LABEL_MAP = {1: "大一", 2: "大二", 3: "大三", 4: "大四", 5: "大五"}


def _get_grade_label(grade: Optional[int]) -> str:
    if grade is None:
        return ""
    return GRADE_LABEL_MAP.get(grade, f"年级{grade}")


# ════════════════════════════════════════════════════════════════════════
# 分类树列头构建
# ════════════════════════════════════════════════════════════════════════

class ColumnHeaderPlan:
    """描述导出 Excel 的列头结构。

    - leaf_columns: 叶子列列表（按导出顺序），每项含 {key, label, category_id, depth, path_ids}
    - max_depth: 分类树的最大嵌套深度（用于确定表头行数）
    - top_level_groups: 顶级分组信息
    """

    def __init__(self):
        self.leaf_columns: List[Dict[str, Any]] = []
        self.max_depth: int = 0
        self.top_level_groups: List[Dict[str, Any]] = []


def _build_header_plan(
    basic_keys: List[str],
    score_category_ids: List[int],
    extra_field_specs: List[Dict[str, Any]],
    all_categories: List[TemplateCategory],
    column_order: Optional[List[Dict[str, str]]] = None,
) -> ColumnHeaderPlan:
    """根据选中的列和分类树构建列头计划。

    Args:
        basic_keys: 选中的基础信息字段 key 列表
        score_category_ids: 选中的评分分类 ID 列表
        extra_field_specs: 选中的扩展字段 [{id, name}, ...]
        all_categories: 全量激活的分类 ORM 列表
        column_order: 可选列排序 [{source, key}, ...]，用于按前端拖拽顺序排列列

    Returns:
        ColumnHeaderPlan 包含叶子列和层级信息
    """
    plan = ColumnHeaderPlan()

    # 构建分类映射
    cat_map: Dict[int, TemplateCategory] = {c.id: c for c in all_categories}

    # 计算每个节点的深度（从根开始）
    def calc_depth(cat_id: int, depth: int = 0) -> int:
        cat = cat_map.get(cat_id)
        if cat is None or cat.parent_id is None:
            return depth
        return calc_depth(cat.parent_id, depth + 1)

    # 获取从根到该节点的路径 ID 列表
    def get_path_ids(cat_id: int) -> List[int]:
        path = []
        current_id = cat_id
        while current_id is not None:
            cat = cat_map.get(current_id)
            if cat is None:
                break
            path.insert(0, current_id)
            current_id = cat.parent_id
        return path

    # 1) 基础信息列（depth=0，无层级分组）
    for key in basic_keys:
        if key in BASIC_FIELD_DEFS:
            plan.leaf_columns.append({
                "key": key,
                "label": BASIC_FIELD_DEFS[key]["label"],
                "source": "basic",
                "category_id": None,
                "depth": 0,
                "path_ids": [key],  # 用 key 作唯一路径标识
                "width": BASIC_FIELD_DEFS[key].get("width", BASIC_COL_WIDTH),
            })

    # 2) 评分分类列（根据树结构计算 depth 和 path）
    for cat_id in score_category_ids:
        cat = cat_map.get(cat_id)
        if cat is None:
            continue
        depth = calc_depth(cat_id)
        path_ids = get_path_ids(cat_id)
        plan.max_depth = max(plan.max_depth, depth)
        plan.leaf_columns.append({
            "key": f"score_{cat_id}",
            "label": f"{cat.name}(分)",
            "source": "score",
            "category_id": cat_id,
            "depth": depth,
            "path_ids": path_ids,
            "width": SCORE_COL_WIDTH,
        })

    # 3) 扩展信息列（depth=0）
    for spec in extra_field_specs:
        fid = spec.get("id")
        fname = spec.get("name", f"字段{fid}")
        plan.leaf_columns.append({
            "key": f"extra_{fid}",
            "label": fname,
            "source": "extra",
            "category_id": None,
            "depth": 0,
            "path_ids": [f"extra_{fid}"],
            "width": 14,
        })

    # 计算总最大深度
    plan.max_depth = max(plan.max_depth, 0)

    # ── 若提供了 column_order，按指定顺序重排 leaf_columns ──
    if column_order:
        ordered: List[Dict[str, Any]] = []
        remaining = list(plan.leaf_columns)
        for entry in column_order:
            source = entry.get("source", "")
            key = entry.get("key", "")
            # 找到匹配的列
            idx = next(
                (i for i, c in enumerate(remaining) if c["source"] == source and c["key"] == key),
                None,
            )
            if idx is not None:
                ordered.append(remaining.pop(idx))
        # 追加未被 column_order 覆盖的列（防御性）
        ordered.extend(remaining)
        plan.leaf_columns = ordered

    # 收集顶级分组信息（用于设置列分组）
    _collect_group_info(plan, cat_map)

    return plan


def _collect_group_info(plan: ColumnHeaderPlan, cat_map: Dict[int, TemplateCategory]) -> None:
    """收集评分列的层级分组信息，用于生成多级表头和列分组。"""
    # 找到所有评分列的路径，按深度组织
    score_cols = [c for c in plan.leaf_columns if c["source"] == "score"]
    if not score_cols:
        return

    # 收集每个深度层级上的唯一节点
    depth_nodes: Dict[int, Dict[int, Dict[str, Any]]] = {}
    for col in score_cols:
        for d_idx, node_id in enumerate(col["path_ids"]):
            if d_idx not in depth_nodes:
                depth_nodes[d_idx] = {}
            if node_id not in depth_nodes[d_idx]:
                cat = cat_map.get(node_id)
                depth_nodes[d_idx][node_id] = {
                    "id": node_id,
                    "name": cat.name if cat else str(node_id),
                    "depth": d_idx,
                }

    plan._depth_nodes = depth_nodes


# ════════════════════════════════════════════════════════════════════════
# Excel 生成器
# ════════════════════════════════════════════════════════════════════════

class ExportService:
    """学生数据导出服务"""

    @staticmethod
    async def export_students(
        db: AsyncSession,
        *,
        basic_keys: List[str],
        score_category_ids: List[int],
        extra_field_specs: List[Dict[str, Any]],
        filters: Dict[str, Any],
        column_order: Optional[List[Dict[str, str]]] = None,
    ) -> io.BytesIO:
        """生成带分层分组的 Excel 文件，返回 BytesIO 流。

        Args:
            db: 数据库会话
            basic_keys: 基础信息字段 key 列表
            score_category_ids: 评分分类 ID 列表
            extra_field_specs: 扩展字段 [{id, name}, ...]
            filters: 筛选条件 {major, grade, enrollmentYear, graduationYear, excludedStudentIds}
            column_order: 可选列排序 [{source: "basic"|"score"|"extra", key: "..."}]

        Returns:
            包含 Excel 文件内容的 BytesIO 流
        """
        # 1. 加载分类树
        result = await db.execute(
            select(TemplateCategory).where(
                TemplateCategory.is_active == True,
                TemplateCategory.is_deleted == False,
            ).order_by(
                TemplateCategory.parent_id.nulls_first(),
                TemplateCategory.sort_order.asc(),
                TemplateCategory.id.asc(),
            )
        )
        all_categories = list(result.scalars().all())

        # 2. 构建列头计划（若提供 column_order，则按指定顺序排列叶子列）
        header_plan = _build_header_plan(
            basic_keys, score_category_ids, extra_field_specs, all_categories,
            column_order=column_order,
        )

        # 3. 查询学生数据
        users = await ExportService._query_students(db, filters)

        # 4. 生成 Excel
        wb = Workbook()
        ws = wb.active
        ws.title = "学生数据"

        ExportService._write_headers(ws, header_plan)
        ExportService._write_data(ws, header_plan, users, all_categories, extra_field_specs)
        ExportService._apply_formatting(ws, header_plan, len(users))

        # 5. 输出到 BytesIO
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    @staticmethod
    async def _query_students(
        db: AsyncSession,
        filters: Dict[str, Any],
    ) -> List[User]:
        """根据筛选条件查询学生列表。"""
        query = select(User).where(User.status == "active")

        if filters.get("major"):
            query = query.where(User.major.ilike(f"%{filters['major']}%"))
        if filters.get("grade") is not None:
            query = query.where(User.grade == filters["grade"])
        if filters.get("enrollmentYear") is not None:
            query = query.where(User.enrollment_year == filters["enrollmentYear"])
        if filters.get("graduationYear") is not None:
            query = query.where(User.graduation_year == filters["graduationYear"])

        query = query.order_by(User.id.asc())
        result = await db.execute(query)
        users = list(result.scalars().all())

        # 过滤排除的学生 ID
        excluded_ids: List[int] = filters.get("excludedStudentIds", [])
        if excluded_ids:
            excluded_set = set(excluded_ids)
            users = [u for u in users if u.id not in excluded_set]

        return users

    @staticmethod
    def _write_headers(ws: Worksheet, plan: ColumnHeaderPlan) -> None:
        """写入多级表头（含合并单元格）和列分组。

        表头结构（从上到下）：
          - 第 1..N 行：评分列的多级分类名称（合并单元格）
          - 第 N+1 行：叶子列名（评分列 + 基础 + 扩展）
        """
        max_depth = plan.max_depth
        # 总分表头行数 = 分类层级深度
        header_rows = max(1, max_depth)

        score_cols = [c for c in plan.leaf_columns if c["source"] == "score"]

        # ── 计算评分列的起始列号 ──
        basic_count = len([c for c in plan.leaf_columns if c["source"] == "basic"])
        score_start_col = basic_count + 1  # 1-indexed

        # ── 写入分类层级表头（仅评分列）──
        if score_cols and max_depth > 0:
            cat_map: Dict[int, Any] = {}
            # 从 plan._depth_nodes 取分类信息
            depth_nodes = getattr(plan, '_depth_nodes', {})

            for depth in range(max_depth):
                row = depth + 1  # 1-indexed
                nodes_at_depth = depth_nodes.get(depth, {})

                # 对评分列进行分组：相邻且同 parent 的列合并
                col_offset = score_start_col
                i = 0
                while i < len(score_cols):
                    col = score_cols[i]
                    path_ids = col["path_ids"]
                    node_id = path_ids[depth] if depth < len(path_ids) else None

                    if node_id is None:
                        # 没有这个深度的节点，跳过
                        i += 1
                        col_offset += 1
                        continue

                    # 找到所有连续的同节点列
                    j = i
                    while j < len(score_cols):
                        next_path = score_cols[j]["path_ids"]
                        next_node = next_path[depth] if depth < len(next_path) else None
                        if next_node == node_id:
                            j += 1
                        else:
                            break

                    # 合并单元格（如果 span > 1）
                    span = j - i
                    node_name = nodes_at_depth.get(node_id, {}).get("name", str(node_id))

                    if span > 1:
                        ws.merge_cells(
                            start_row=row, start_column=col_offset,
                            end_row=row, end_column=col_offset + span - 1
                        )

                    cell = ws.cell(row=row, column=col_offset, value=node_name)
                    cell.font = SUBHEADER_FONT
                    cell.fill = SUBHEADER_FILL
                    cell.alignment = CENTER_ALIGN
                    cell.border = THIN_BORDER

                    # 设置列分组（Outline Level）
                    outline_level = depth + 1
                    for c_idx in range(col_offset, col_offset + span):
                        col_letter = get_column_letter(c_idx)
                        if ws.column_dimensions[col_letter].outline_level is None or \
                           ws.column_dimensions[col_letter].outline_level < outline_level:
                            ws.column_dimensions[col_letter].outline_level = outline_level
                            # 默认折叠第二层及以下
                            if depth >= 1:
                                ws.column_dimensions[col_letter].hidden = False

                    i = j
                    col_offset += span

        # ── 写入叶子列名行 ──
        leaf_row = max_depth + 1 if score_cols and max_depth > 0 else 1
        for col_idx, col in enumerate(plan.leaf_columns):
            cell_col = col_idx + 1
            cell = ws.cell(row=leaf_row, column=cell_col, value=col["label"])
            cell.font = LEAF_HEADER_FONT if col["source"] == "score" else HEADER_FONT
            cell.fill = LEAF_HEADER_FILL if col["source"] == "score" else HEADER_FILL
            cell.alignment = CENTER_ALIGN
            cell.border = THIN_BORDER
            # 设置列宽
            ws.column_dimensions[get_column_letter(cell_col)].width = col.get("width", 14)

            # 评分列 Outline Level
            if col["source"] == "score":
                score_depth = col.get("depth", 0)
                if score_depth > 0:
                    col_letter = get_column_letter(cell_col)
                    # 子列至少设为 depth 级别的 outline（父级表头已设 depth+1）
                    current = ws.column_dimensions[col_letter].outline_level or 0
                    ws.column_dimensions[col_letter].outline_level = max(current, score_depth)

        # ── 如果有多行表头，合并基础/扩展列的表头（垂直合并）──
        if leaf_row > 1:
            for col_idx, col in enumerate(plan.leaf_columns):
                if col["source"] in ("basic", "extra"):
                    cell_col = col_idx + 1
                    if leaf_row > 1:
                        ws.merge_cells(
                            start_row=1, start_column=cell_col,
                            end_row=leaf_row, end_column=cell_col
                        )
                        # 重新写第一行单元格样式
                        cell_top = ws.cell(row=1, column=cell_col)
                        cell_top.font = HEADER_FONT
                        cell_top.fill = HEADER_FILL
                        cell_top.alignment = CENTER_ALIGN
                        cell_top.border = THIN_BORDER

    @staticmethod
    def _write_data(
        ws: Worksheet,
        plan: ColumnHeaderPlan,
        users: List[User],
        all_categories: List[TemplateCategory],
        extra_field_specs: List[Dict[str, Any]],
    ) -> None:
        """写入学生数据行。"""
        header_rows = max(1, plan.max_depth + 1 if any(
            c["source"] == "score" for c in plan.leaf_columns
        ) and plan.max_depth > 0 else 1)

        # 构建分类 ID→name 映射
        cat_map = {c.id: c for c in all_categories}

        for row_idx, user in enumerate(users):
            row = header_rows + 1 + row_idx  # 1-indexed, skip headers

            # 提取学号
            student_id = User.extract_student_id(user.username) or ""

            for col_idx, col in enumerate(plan.leaf_columns):
                cell_col = col_idx + 1
                cell = ws.cell(row=row, column=cell_col)
                cell.font = DATA_FONT
                cell.border = THIN_BORDER
                cell.alignment = CENTER_ALIGN if col["source"] != "basic" else LEFT_ALIGN

                if col["source"] == "basic":
                    key = col["key"]
                    if key == "fullName":
                        cell.value = user.full_name or ""
                    elif key == "studentId":
                        cell.value = student_id
                    elif key == "major":
                        cell.value = user.major or ""
                    elif key == "grade":
                        cell.value = _get_grade_label(user.grade)
                    elif key == "enrollmentYear":
                        cell.value = user.enrollment_year or ""
                    elif key == "graduationYear":
                        cell.value = user.graduation_year or ""
                    elif key == "phone":
                        cell.value = user.phone or ""

                elif col["source"] == "score":
                    cat_id = col["category_id"]
                    score_info = user.score_info or {}
                    scores = score_info.get("scores", {})
                    cat_score = scores.get(str(cat_id), {})
                    score_val = cat_score.get("score")
                    if score_val is not None:
                        cell.value = float(score_val)
                        cell.number_format = '0.00'
                    else:
                        cell.value = "-"
                    cell.alignment = CENTER_ALIGN

                elif col["source"] == "extra":
                    field_id = None
                    for spec in extra_field_specs:
                        if f"extra_{spec['id']}" == col["key"]:
                            field_id = spec["id"]
                            break
                    if field_id is not None:
                        extra_info = user.extra_info or {}
                        val = extra_info.get(f"f_{field_id}", "")
                        cell.value = val if val is not None else ""
                    else:
                        cell.value = ""

    @staticmethod
    def _apply_formatting(
        ws: Worksheet,
        plan: ColumnHeaderPlan,
        student_count: int,
    ) -> None:
        """应用最终格式化：冻结窗格、自动筛选、打印设置。"""
        header_rows = max(1, plan.max_depth + 1 if any(
            c["source"] == "score" for c in plan.leaf_columns
        ) and plan.max_depth > 0 else 1)

        # 冻结表头
        ws.freeze_panes = ws.cell(row=header_rows + 1, column=1)

        # 自动筛选
        total_cols = len(plan.leaf_columns)
        if total_cols > 0:
            ws.auto_filter.ref = f"A{header_rows}:{get_column_letter(total_cols)}{header_rows + student_count}"

        # 启用列分组折叠按钮（默认显示折叠按钮）
        ws.sheet_properties.outlinePr.summaryRight = False  # 折叠按钮在右侧


# ════════════════════════════════════════════════════════════════════════
# 便捷函数
# ════════════════════════════════════════════════════════════════════════

async def generate_export_excel(
    db: AsyncSession,
    basic_keys: List[str],
    score_category_ids: List[int],
    extra_field_specs: List[Dict[str, Any]],
    filters: Dict[str, Any],
    column_order: Optional[List[Dict[str, str]]] = None,
) -> io.BytesIO:
    """便捷函数：生成导出 Excel 并返回 BytesIO。"""
    return await ExportService.export_students(
        db,
        basic_keys=basic_keys,
        score_category_ids=score_category_ids,
        extra_field_specs=extra_field_specs,
        filters=filters,
        column_order=column_order,
    )
