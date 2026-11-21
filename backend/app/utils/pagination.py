"""分页计算工具。"""

from __future__ import annotations


def compute_offset(page: int, page_size: int) -> int:
    """把页码转换为 SQL OFFSET。"""
    return max(page - 1, 0) * page_size


def compute_pages(total: int, page_size: int) -> int:
    """计算总页数，空数据返回 0。"""
    if page_size <= 0:
        return 0
    return (total + page_size - 1) // page_size
