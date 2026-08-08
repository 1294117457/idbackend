"""学生数据导出 Service（v8.1 - 通用列树 + 行展开自动推断 + 不持久化）

数据流：
    1. 接收 ExportUsersRequest（含 columns 树、filters）
    2. 校验列树（白名单 + 层级约束 + 字段完整性）
    3. 查学生（按 filters + studentIds/excludedIds）
    4. 预加载 applications（按 category_id 收集 PASSED 列表）+ extra_info_field（name → id）
    5. 自动推断每个 category 的行展开（看子列含 application_*）
    6. openpyxl 生成多级表头（DFS 算 col_start/col_end + row_start/row_end）+ 数据行
    7. 流式返回 xlsx 文件

详见 docs/docs-backend/导出表格/export-后端实现方案.md
"""
from __future__ import annotations

import io
import logging
from collections import defaultdict
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.schemas.errors import BadRequestError
from src.app.schemas.export import (
    APPLICATION_APPLY,
    APPLICATION_ATTR,
    APPLICATION_GAIN,
    APPLICATION_REMARK,
    APPLICATION_STATUS,
    CATEGORY,
    CONSTRAINED_SOURCES,
    ExportColumnNode,
    ExportUsersRequest,
    USER_BASIC,
    USER_BASIC_FIELDS,
    USER_EXTRA,
)
from src.models.application import Application, ApplicationStatus
from src.models.extra_info_field import ExtraInfoField
from src.models.user import User

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════
# 节点坐标分配（DFS）
# ════════════════════════════════════════════════════════════════════════

class NodeCoord:
    """列树节点的 Excel 坐标（后端运行时计算，前端不感知）"""
    __slots__ = ("node", "col_start", "col_end", "row_start", "row_end")

    def __init__(self, node: ExportColumnNode) -> None:
        self.node = node
        self.col_start = 0
        self.col_end = 0
        self.row_start = 0
        self.row_end = 0


def _assign_coordinates(columns: List[ExportColumnNode]) -> List[NodeCoord]:
    """DFS 给每个节点分配 col_start/col_end + row_start/row_end。

    col 范围：后序遍历，叶子 [start,start]；父 [first.start, last.end]
    row 范围：前序遍历，父 row=r，子 row=r+1；父 row_end=r（父只占 1 行）
    """
    # 先建全树 coord 映射（确保子节点在递归时已注册）
    coords_map: Dict[str, NodeCoord] = {}

    def get_or_create(node: ExportColumnNode) -> NodeCoord:
        if node.id not in coords_map:
            coords_map[node.id] = NodeCoord(node)
        return coords_map[node.id]

    # 先注册全部节点
    def register_all(nodes: List[ExportColumnNode]) -> None:
        for n in nodes:
            get_or_create(n)
            if n.children:
                register_all(n.children)

    register_all(columns)
    coords = [get_or_create(n) for n in columns]

    # DFS col 范围（后序）
    def dfs_col(coord: NodeCoord, start_col: int) -> int:
        children_sorted = sorted(coord.node.children, key=lambda c: c.sortOrder)
        if not children_sorted:
            coord.col_start = start_col
            coord.col_end = start_col
            return start_col + 1
        cur = start_col
        for child_node in children_sorted:
            child_coord = get_or_create(child_node)
            cur = dfs_col(child_coord, cur)
        coord.col_start = start_col
        coord.col_end = cur - 1
        return cur

    # DFS row 范围（前序）：父 row=r，子 row=r+1；父 row_end=r（占 1 行）
    def dfs_row(coord: NodeCoord, row: int) -> int:
        coord.row_start = row
        children_sorted = sorted(coord.node.children, key=lambda c: c.sortOrder)
        if not children_sorted:
            coord.row_end = row
            return row + 1
        # 所有子节点都在同一行 row+1；递归取最深的 row_end 作为父的"占用结束行"
        max_child_end = row
        for child_node in children_sorted:
            child_coord = get_or_create(child_node)
            child_end = dfs_row(child_coord, row + 1)
            max_child_end = max(max_child_end, child_end)
        coord.row_end = row  # 父节点只占 1 行
        return max_child_end + 1  # cursor 推进到最深子树后

    # 第一遍：col 分配（按顶级顺序累加 col cursor）
    col_cursor = 0
    for coord in coords:
        col_cursor = dfs_col(coord, col_cursor)

    # 第二遍：row 分配（每个顶级节点独立从 row=0 开始 —— 顶级都在第 1 行）
    for coord in coords:
        dfs_row(coord, 0)

    # ★ 修复：返回 coords_map.values() 而不是 coords
    # 因为 dfs_col / dfs_row 会把子节点注册到 coords_map，但 coords 只包含顶级
    return list(coords_map.values())


# ════════════════════════════════════════════════════════════════════════
# 列树校验
# ════════════════════════════════════════════════════════════════════════

def _validate_columns(columns: List[ExportColumnNode]) -> None:
    """递归校验列树合法性（白名单 + 层级约束 + 字段完整性）。

    抛出 BadRequestError 时直接返回 400 + 错误信息。
    """
    seen_ids: Set[str] = set()
    valid_sources = set(CONSTRAINED_SOURCES) | {USER_BASIC, USER_EXTRA, CATEGORY}

    def walk(node: ExportColumnNode, parent: Optional[ExportColumnNode]) -> None:
        # 1. source 白名单（理论上 Pydantic Literal 已拦截，这里防御性再校验）
        if node.source not in valid_sources:
            raise BadRequestError(
                f"列 '{node.label}' 的 source='{node.source}' 不在白名单内"
            )

        # 2. id 唯一
        if node.id in seen_ids:
            raise BadRequestError(f"列树节点 id 重复: {node.id}")
        seen_ids.add(node.id)

        # 3. parentId 指向合法父节点
        expected_parent_id = parent.id if parent else None
        if node.parentId != expected_parent_id:
            raise BadRequestError(
                f"节点 '{node.label}' 的 parentId={node.parentId} "
                f"与实际父 '{expected_parent_id}' 不一致"
            )

        # 4. ★ 层级约束：application_* 必须挂 category 下
        if node.source in CONSTRAINED_SOURCES:
            if parent is None or parent.source != CATEGORY:
                parent_label = parent.label if parent else "顶级"
                parent_source = parent.source if parent else "(none)"
                raise BadRequestError(
                    f"列 '{node.label}' (source={node.source}) 必须挂在 category 节点下，"
                    f"当前父节点是 '{parent_label}' (source={parent_source})"
                )

        # 5. application_attr 必须有 ruleName
        if node.source == APPLICATION_ATTR and not node.ruleName:
            raise BadRequestError(
                f"application_attr 列 '{node.label}' 必须指定 ruleName"
            )

        # 6. user_extra 必须有 fieldPath
        if node.source == USER_EXTRA and not node.fieldPath:
            raise BadRequestError(
                f"user_extra 列 '{node.label}' 必须指定 fieldPath"
            )

        # 7. user_basic 必须有 basicField（且必须在白名单内）
        if node.source == USER_BASIC:
            if not node.basicField:
                raise BadRequestError(
                    f"user_basic 列 '{node.label}' 必须指定 basicField"
                )
            if node.basicField not in USER_BASIC_FIELDS:
                raise BadRequestError(
                    f"user_basic 列 '{node.label}' 的 basicField='{node.basicField}' "
                    f"不在白名单 {sorted(USER_BASIC_FIELDS)} 内"
                )

        # 8. category 必须有 categoryId
        if node.source == CATEGORY and node.categoryId is None:
            raise BadRequestError(
                f"category 节点 '{node.label}' 必须指定 categoryId"
            )

        # 9. category 节点本身不应有 user_* 字段（防御）
        if node.source == CATEGORY:
            if node.basicField or node.fieldPath:
                raise BadRequestError(
                    f"category 节点 '{node.label}' 不应携带 basicField / fieldPath"
                )

        # 10. 递归子列
        for child in node.children:
            walk(child, node)

    for node in columns:
        walk(node, None)


# ════════════════════════════════════════════════════════════════════════
# 行展开自动推断
# ════════════════════════════════════════════════════════════════════════

def _walk_descendants(node: ExportColumnNode):
    """DFS 遍历 node 全部后代（含 node 自己）"""
    yield node
    for child in node.children:
        yield from _walk_descendants(child)


def _category_has_application_columns(cat_node: ExportColumnNode) -> bool:
    """判断 category 节点的子树里是否含 application_* 字段"""
    for n in _walk_descendants(cat_node):
        if n.source in CONSTRAINED_SOURCES:
            return True
    return False


def _infer_max_app_count(
    category_nodes: List[ExportColumnNode],
    app_cache: Dict[int, Dict[int, List[Application]]],
    user_id: int,
    max_per_cat: int,
) -> int:
    """对单个学生，返回所有"按 application 展开"的 category 中 PASSED application 数的最大值"""
    max_count = 0
    for cat in category_nodes:
        if not _category_has_application_columns(cat):
            continue
        cat_id = cat.categoryId
        if cat_id is None:
            continue
        apps = app_cache.get(user_id, {}).get(cat_id, [])
        max_count = max(max_count, min(len(apps), max_per_cat))
    return max_count


# ════════════════════════════════════════════════════════════════════════
# 取值逻辑
# ════════════════════════════════════════════════════════════════════════

def _resolve_user_basic_value(user: User, basic_field: str) -> Any:
    """user_basic 列取值"""
    # studentId 特殊处理：优先 users.student_id，fallback 到 extract_student_id(username)
    if basic_field == "studentId":
        if user.student_id:
            return user.student_id
        return User.extract_student_id(user.username) or ""
    if basic_field == "fullName":
        return user.full_name or ""
    if basic_field == "phone":
        return user.phone or ""
    if basic_field == "department":
        return user.department or ""
    if basic_field == "major":
        return user.major or ""
    if basic_field == "grade":
        return user.grade if user.grade is not None else ""
    if basic_field == "enrollmentYear":
        return user.enrollment_year if user.enrollment_year is not None else ""
    if basic_field == "graduationYear":
        return user.graduation_year if user.graduation_year is not None else ""
    if basic_field == "gender":
        return user.gender or ""
    if basic_field == "idCardNumber":
        return user.id_card_number or ""
    if basic_field == "username":
        return user.username or ""
    if basic_field == "lastLoginAt":
        return user.last_login_at or ""
    return ""


def _transform_grade(value: Any) -> Any:
    """grade 1/2/3/4 → "大一"/"大二"/"大三"/"大四"（≤4）"""
    if isinstance(value, int) and 1 <= value <= 4:
        return {1: "大一", 2: "大二", 3: "大三", 4: "大四"}.get(value, value)
    return value


def _resolve_user_extra_value(
    user: User, field_path: str, extra_field_id: int
) -> Any:
    """user_extra 列取值（extra_info JSON 中 f_{field_id} 取值）"""
    extra = user.extra_info or {}
    key = f"f_{extra_field_id}"
    return extra.get(key, "")


def _resolve_app_value(app: Application, col: ExportColumnNode) -> Any:
    """application_* 列取值（按 row_idx 已定位到 app）"""
    if col.source == APPLICATION_APPLY:
        return float(app.apply_score) if app.apply_score is not None else ""
    if col.source == APPLICATION_GAIN:
        return float(app.gain_score) if app.gain_score is not None else ""
    if col.source == APPLICATION_ATTR:
        rule_info = app.rule_info or {}
        if col.ruleName is None:
            return ""
        return rule_info.get(col.ruleName, "")
    if col.source == APPLICATION_STATUS:
        return app.status or ""
    if col.source == APPLICATION_REMARK:
        # Application ORM 无 remark 字段（remark 在 ApplicationOperation 表），
        # v8.1 暂时返回空；未来如需可从 ApplicationOperation 拼装最近一条 remark。
        return ""
    return ""


# ════════════════════════════════════════════════════════════════════════
# 数据查询
# ════════════════════════════════════════════════════════════════════════

async def _query_students(
    db: AsyncSession,
    filters: Any,
    student_ids: Optional[List[int]],
    excluded_ids: Optional[List[int]],
) -> List[User]:
    """按过滤条件查学生（admin 用）"""
    stmt = select(User)

    if filters.username:
        stmt = stmt.where(User.username.ilike(f"%{filters.username}%"))
    if filters.fullName:
        stmt = stmt.where(User.full_name.ilike(f"%{filters.fullName}%"))
    if filters.major:
        stmt = stmt.where(User.major.ilike(f"%{filters.major}%"))
    if filters.department:
        stmt = stmt.where(User.department.ilike(f"%{filters.department}%"))
    if filters.grade is not None:
        stmt = stmt.where(User.grade == filters.grade)
    if filters.enrollmentYear is not None:
        stmt = stmt.where(User.enrollment_year == filters.enrollmentYear)
    if filters.graduationYear is not None:
        stmt = stmt.where(User.graduation_year == filters.graduationYear)

    if student_ids:
        stmt = stmt.where(User.id.in_(student_ids))
    if excluded_ids:
        stmt = stmt.where(User.id.notin_(excluded_ids))

    # 按 id ASC 保持稳定顺序（不依赖 created_at，避免同 created_at 的乱序）
    stmt = stmt.order_by(User.id.asc())

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _preload_applications(
    db: AsyncSession,
    user_ids: List[int],
    category_ids: List[int],
) -> Dict[int, Dict[int, List[Application]]]:
    """预加载所有相关 application：app_cache[user_id][category_id] = [PASSED apps, ...]

    注意：category_id 直接来自 application.category_id（外键到 template_category.id），
    而非 application.template.category_id。Application.category_id 字段已直接持有分类 id。
    """
    if not user_ids or not category_ids:
        return {}

    stmt = (
        select(Application)
        .where(Application.user_id.in_(user_ids))
        .where(Application.category_id.in_(category_ids))
        .where(Application.status == ApplicationStatus.PASSED.value)
        .order_by(Application.user_id.asc(), Application.category_id.asc(), Application.id.asc())
    )
    result = await db.execute(stmt)
    apps = list(result.scalars().all())

    cache: Dict[int, Dict[int, List[Application]]] = defaultdict(lambda: defaultdict(list))
    for app in apps:
        cat_id = app.category_id
        if cat_id is None:
            continue
        cache[app.user_id][cat_id].append(app)
    return cache


async def _preload_extra_field_map(
    db: AsyncSession,
    field_paths: List[str],
) -> Dict[str, int]:
    """把 extra_info_field.name → id，建立映射

    若有同名（理论上不应有，业务侧保证），取最小 id。
    """
    if not field_paths:
        return {}
    stmt = select(ExtraInfoField).where(ExtraInfoField.name.in_(field_paths))
    result = await db.execute(stmt)
    fields = list(result.scalars().all())
    # 防御性：name 重名时取最小 id（前端按 name 引用，要求唯一）
    by_name: Dict[str, int] = {}
    seen_names: Dict[str, List[int]] = defaultdict(list)
    for f in fields:
        seen_names[f.name].append(f.id)
    for name, ids in seen_names.items():
        by_name[name] = min(ids)
        if len(ids) > 1:
            logger.warning(
                f"extra_info_field.name='{name}' 存在多个 id {ids}，取最小 {min(ids)}"
            )
    return by_name


# ════════════════════════════════════════════════════════════════════════
# 列树遍历辅助
# ════════════════════════════════════════════════════════════════════════

def _collect_category_nodes(columns: List[ExportColumnNode]) -> List[ExportColumnNode]:
    """收集列树里所有 category 节点（递归）"""
    result: List[ExportColumnNode] = []
    for col in columns:
        if col.source == CATEGORY:
            result.append(col)
        for child in col.children:
            result.extend(_collect_category_nodes([child]))
    return result


def _collect_field_paths(columns: List[ExportColumnNode]) -> List[str]:
    """收集所有 user_extra 列的 fieldPath（用于预加载）"""
    paths: List[str] = []
    for col in _walk_all(columns):
        if col.source == USER_EXTRA and col.fieldPath:
            paths.append(col.fieldPath)
    return list(set(paths))  # 去重


def _collect_category_ids(category_nodes: List[ExportColumnNode]) -> List[int]:
    """收集所有 category 节点的 categoryId（用于预加载 application）"""
    return [n.categoryId for n in category_nodes if n.categoryId is not None]


def _walk_all(columns: List[ExportColumnNode]):
    """遍历全部节点（含顶级和深层子列）"""
    for col in columns:
        yield from _walk_descendants(col)


def _build_by_id_map(columns: List[ExportColumnNode]) -> Dict[str, ExportColumnNode]:
    """id → node 映射（用于祖先查找）"""
    return {n.id: n for n in _walk_all(columns)}


def _find_ancestor_category_id_in_map(
    col: ExportColumnNode,
    by_id: Dict[str, ExportColumnNode],
) -> Optional[int]:
    """向上找最近的 category 祖先，返回 categoryId（找不到返回 None）"""
    node = col
    while node is not None:
        if node.source == CATEGORY and node.categoryId is not None:
            return node.categoryId
        parent_id = node.parentId
        if parent_id is None:
            return None
        node = by_id.get(parent_id)
    return None


# ════════════════════════════════════════════════════════════════════════
# Excel 渲染
# ════════════════════════════════════════════════════════════════════════

# 表头样式：粗体 + 居中，无填充色（避免遮挡表格）
_HEADER_FONT = Font(bold=False)
_HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _render_header(ws: Worksheet, coords: List[NodeCoord]) -> int:
    """渲染多级表头 + merge_cells。返回表头总行数。"""
    if not coords:
        return 0

    max_row = max(c.row_end for c in coords)

    # 1. 填标签（只填左上角；非叶子的 merge 由后续步骤完成）
    for coord in coords:
        cell = ws.cell(
            row=coord.row_start + 1,  # openpyxl 1-based
            column=coord.col_start + 1,
            value=coord.node.label,
        )
        cell.font = _HEADER_FONT
        cell.alignment = _HEADER_ALIGN

    # 2. 合并非叶子节点（横向 + 父节点纵向）
    for coord in coords:
        is_leaf = not coord.node.children
        if is_leaf:
            continue
        # 横向合并（多个子列 → 1 个父标签）
        if coord.col_end > coord.col_start:
            ws.merge_cells(
                start_row=coord.row_start + 1,
                end_row=coord.row_end + 1,
                start_column=coord.col_start + 1,
                end_column=coord.col_end + 1,
            )
        # 父节点本身已填值，不需要再纵向合并

    return max_row + 1


def _render_data(
    ws: Worksheet,
    start_row: int,
    user: User,
    coords: List[NodeCoord],
    app_cache: Dict[int, Dict[int, List[Application]]],
    extra_field_map: Dict[str, int],
    by_id: Dict[str, ExportColumnNode],
    max_per_cat: int,
) -> None:
    """渲染单个学生的数据行。

    算法：
    1. 收集所有 category 节点
    2. 对每个 category 判断"按 application 展开"还是"按 single 展开"
    3. 总行数 = max(所有 application 类 category 的 PASSED 数, 1)
    4. 对每行 r，每个叶子列算值
       - user_basic / user_extra → 用 user 自身（每行重复同一值）
       - application_* → 用所在 category 的第 r 个 application（如果 r 超出，补空）
    """
    # 提取所有 category 节点
    category_nodes: List[ExportColumnNode] = []
    for coord in coords:
        if coord.node.source == CATEGORY:
            category_nodes.append(coord.node)

    # 计算每个 category 的"目标行数"
    cat_target_rows: Dict[int, int] = {}
    for cat_node in category_nodes:
        cat_id = cat_node.categoryId
        if cat_id is None:
            continue
        if _category_has_application_columns(cat_node):
            apps = app_cache.get(user.id, {}).get(cat_id, [])
            cat_target_rows[cat_id] = min(max(len(apps), 1), max_per_cat)
        else:
            cat_target_rows[cat_id] = 1

    # 取所有 application 类 category 行数最大值（行对齐）
    max_count = max((c for c in cat_target_rows.values() if c > 1), default=1)
    if max_count < 1:
        max_count = 1

    # 渲染每一行
    for r in range(max_count):
        excel_row = start_row + r
        for coord in coords:
            node = coord.node
            if not node.children:
                # 叶子节点：写值
                value = _resolve_leaf_value(
                    user=user,
                    col=node,
                    row_idx=r,
                    app_cache=app_cache,
                    extra_field_map=extra_field_map,
                    by_id=by_id,
                    max_per_cat=max_per_cat,
                )
                cell = ws.cell(
                    row=excel_row + 1,
                    column=coord.col_start + 1,
                    value=value,
                )
            else:
                # 非叶子节点：什么都不做（merge 已完成）
                pass


def _resolve_leaf_value(
    user: User,
    col: ExportColumnNode,
    row_idx: int,
    app_cache: Dict[int, Dict[int, List[Application]]],
    extra_field_map: Dict[str, int],
    by_id: Dict[str, ExportColumnNode],
    max_per_cat: int,
) -> Any:
    """计算单个叶子节点在指定 row 的值"""
    if col.source == USER_BASIC:
        v = _resolve_user_basic_value(user, col.basicField or "")
        if col.cellTransform == "grade":
            v = _transform_grade(v)
        return v

    if col.source == USER_EXTRA:
        if not col.fieldPath:
            return ""
        field_id = extra_field_map.get(col.fieldPath)
        if field_id is None:
            return ""
        return _resolve_user_extra_value(user, col.fieldPath, field_id)

    if col.source in CONSTRAINED_SOURCES:
        cat_id = _find_ancestor_category_id_in_map(col, by_id)
        if cat_id is None:
            return ""
        apps = app_cache.get(user.id, {}).get(cat_id, [])
        if row_idx >= len(apps):
            return ""
        app = apps[row_idx]
        return _resolve_app_value(app, col)

    return ""


# ════════════════════════════════════════════════════════════════════════
# 对外主入口
# ════════════════════════════════════════════════════════════════════════

class ExportService:
    """学生数据导出服务（v8.1）

    提供一个静态方法 stream_students_xlsx，返回 (bytes, filename)。
    调用方把 bytes 包成 StreamingResponse。
    """

    @staticmethod
    async def stream_students_xlsx(
        db: AsyncSession,
        req: ExportUsersRequest,
    ) -> Tuple[bytes, str]:
        """生成 Excel 文件字节流

        Returns:
            (xlsx_bytes, filename_with_extension)
        """
        # 1. 校验列树
        _validate_columns(req.columns)

        # 2. 收集预加载所需数据
        category_nodes = _collect_category_nodes(req.columns)
        category_ids = _collect_category_ids(category_nodes)
        field_paths = _collect_field_paths(req.columns)

        # 3. 查学生
        users = await _query_students(
            db, req.filters, req.studentIds, req.excludedIds
        )

        if not users:
            # 空表也算合法（生成只有表头的 xlsx）
            pass

        # 4. 预加载 applications + extra_field_map
        user_ids = [u.id for u in users]
        app_cache = await _preload_applications(db, user_ids, category_ids)
        extra_field_map = await _preload_extra_field_map(db, field_paths)

        # 5. 校验 extra_field_map 完整性（fieldPath 都能解析到 id）
        for fp in field_paths:
            if fp not in extra_field_map:
                raise BadRequestError(
                    f"扩展信息字段名 '{fp}' 在 extra_info_field 表中不存在"
                )

        # 6. 分配坐标 + 建 by_id_map
        coords = _assign_coordinates(req.columns)
        by_id = _build_by_id_map(req.columns)

        # 7. 创建 workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "学生数据"

        # 8. 渲染表头
        header_row_count = _render_header(ws, coords)

        # 9. 列宽自适应（按 label 字符数粗算）
        for coord in coords:
            col_letter = get_column_letter(coord.col_start + 1)
            # 中文 1 字 = 2 英文字符宽
            label_width = sum(2 if ord(ch) > 127 else 1 for ch in coord.node.label)
            ws.column_dimensions[col_letter].width = max(label_width + 4, 12)

        # 10. 渲染数据
        max_per_cat = req.maxApplicationsPerCategory
        for user in users:
            _render_data(
                ws=ws,
                start_row=header_row_count,
                user=user,
                coords=coords,
                app_cache=app_cache,
                extra_field_map=extra_field_map,
                by_id=by_id,
                max_per_cat=max_per_cat,
            )

        # 11. 冻结表头
        if header_row_count > 0:
            ws.freeze_panes = ws.cell(row=header_row_count + 1, column=1)

        # 12. 写入 bytes
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        xlsx_bytes = buf.getvalue()

        # 13. 文件名（sanitize 一下，避免非法字符）
        safe_name = _sanitize_filename(req.fileName)
        date_suffix = _today_yyyymmdd()
        filename = f"{safe_name}-{date_suffix}.xlsx"

        return xlsx_bytes, filename


def _sanitize_filename(name: str) -> str:
    """清洗文件名（去路径分隔符、特殊字符）"""
    # Windows 不允许的字符: < > : " / \ | ? *
    bad_chars = '<>:"/\\|?*'
    result = "".join("_" if c in bad_chars else c for c in name).strip()
    if not result:
        result = "students"
    return result[:50]  # 截断


def _today_yyyymmdd() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d")


__all__ = ["ExportService"]
