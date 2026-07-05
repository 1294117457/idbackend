"""通用分页响应容器（跨模块复用）

约定：
- Page[T] 提供 .from_list_to_page() 工厂方法，service 层组装后返回 Page 实例
- 列表场景的 VO 通过继承 Page[T] 形成语义别名（如 FileListVO(Page[FileVO])）
- 与文件模块早期版本兼容：src.app.schemas 仍对外导出 Page
"""
from typing import Generic, List, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """通用分页响应容器

    字段约定（与前端约定一致）：
    - list      数据列表
    - total     总记录数
    - pageNum   当前页（1-indexed）
    - pageSize  每页大小
    - pages     总页数（向上取整，0 表示无数据）
    """

    list: List[T]
    total: int
    pageNum: int
    pageSize: int
    pages: int

    @classmethod
    def from_list_to_page(
        cls,
        items: List[T],
        total: int,
        page_num: int,
        page_size: int,
    ) -> "Page[T]":
        """根据总数与分页大小自动计算 pages。

        服务层语义命名：from_list_to_page —— "从 list 与分页元数据 → Page 容器"。
        与各 VO 的 from_orm_to_vo 风格对称（from_xxx_to_yyy）。
        """
        pages = (total + page_size - 1) // page_size if total > 0 else 0
        return cls(
            list=items,
            total=total,
            pageNum=page_num,
            pageSize=page_size,
            pages=pages,
        )


__all__ = ["Page"]
