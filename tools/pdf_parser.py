"""PDF text extraction — B.

策略：默认走 pypdf（快），文本太少时自动 fallback 到 pdfplumber（layout-aware）。
两种输入：文件路径 (Path/str) 或 bytes（web 上传场景）。

不抛异常：解析失败返回空字符串 + 写日志，让上层 agent 决定怎么处理。
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)

PdfSource = Union[Path, str, bytes]

# 字符数低于这个值 → 认为 pypdf 抽取失败，触发 pdfplumber fallback
MIN_TEXT_CHARS_FOR_PYPDF_SUCCESS = 100


def _to_bytes_io(source: PdfSource) -> BytesIO:
    """把任意输入归一化成可重复读取的 BytesIO。"""
    if isinstance(source, bytes):
        return BytesIO(source)
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    return BytesIO(path.read_bytes())


def _extract_with_pypdf(stream: BytesIO) -> list[str]:
    """用 pypdf 按页抽取文本。失败返回空列表。"""
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("pypdf not installed, skipping pypdf strategy")
        return []

    try:
        stream.seek(0)
        reader = PdfReader(stream)
        return [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as exc:
        logger.warning("pypdf extraction failed: %s", exc)
        return []


def _extract_with_pdfplumber(stream: BytesIO) -> list[str]:
    """用 pdfplumber 按页抽取（layout-aware，慢但更准）。失败返回空列表。"""
    try:
        import pdfplumber
    except ImportError:
        logger.warning("pdfplumber not installed, skipping pdfplumber strategy")
        return []

    try:
        stream.seek(0)
        with pdfplumber.open(stream) as pdf:
            return [(page.extract_text() or "").strip() for page in pdf.pages]
    except Exception as exc:
        logger.warning("pdfplumber extraction failed: %s", exc)
        return []


def extract_pages(source: PdfSource, *, prefer_layout: bool = False) -> list[str]:
    """按页抽取 PDF 文本。

    Args:
        source: 文件路径 (Path/str) 或 PDF bytes
        prefer_layout: True 时直接用 pdfplumber（保留布局，慢）；
                       False 时先用 pypdf（快），不行 fallback pdfplumber

    Returns:
        每页一个字符串的列表。解析完全失败返回 [].
    """
    try:
        stream = _to_bytes_io(source)
    except FileNotFoundError as exc:
        logger.warning(str(exc))
        return []

    if prefer_layout:
        return _extract_with_pdfplumber(stream)

    pages = _extract_with_pypdf(stream)
    total_chars = sum(len(p) for p in pages)
    if total_chars >= MIN_TEXT_CHARS_FOR_PYPDF_SUCCESS:
        return pages

    logger.info(
        "pypdf returned %d chars (< %d threshold), falling back to pdfplumber",
        total_chars,
        MIN_TEXT_CHARS_FOR_PYPDF_SUCCESS,
    )
    return _extract_with_pdfplumber(stream)


def extract_text(source: PdfSource, *, prefer_layout: bool = False) -> str:
    """抽取整份 PDF 文本，按页用双换行连接。"""
    pages = extract_pages(source, prefer_layout=prefer_layout)
    return "\n\n".join(p for p in pages if p)


__all__ = ["extract_pages", "extract_text", "PdfSource"]
