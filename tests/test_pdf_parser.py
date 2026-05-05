"""PDF parser tests — B.

用 data/cea_standard_lease/ 下的真实 CEA PDF 做 fixture。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.pdf_parser import extract_pages, extract_text

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "cea_standard_lease"
HDB_TEMPLATE = DATA_DIR / "Tenancy Agreement Template for HDB Flats.pdf"


def test_extract_text_from_real_cea_pdf_returns_substantive_content():
    text = extract_text(HDB_TEMPLATE)

    assert len(text) > 1000, "CEA HDB tenancy template should be substantial"
    # 标准租约模板必然包含的关键词
    lower = text.lower()
    assert "tenant" in lower
    assert "landlord" in lower


def test_extract_pages_returns_per_page_list():
    pages = extract_pages(HDB_TEMPLATE)

    assert len(pages) > 1, "HDB tenancy template is multi-page"
    assert all(isinstance(p, str) for p in pages)
    # 至少有一页有实质内容
    assert any(len(p) > 200 for p in pages)


def test_extract_text_accepts_bytes_input():
    pdf_bytes = HDB_TEMPLATE.read_bytes()
    text = extract_text(pdf_bytes)

    assert len(text) > 1000


def test_extract_text_accepts_str_path():
    text = extract_text(str(HDB_TEMPLATE))

    assert len(text) > 1000


def test_missing_file_returns_empty_not_raise():
    text = extract_text("does/not/exist.pdf")

    assert text == ""


def test_corrupt_bytes_returns_empty_not_raise():
    text = extract_text(b"this is not a pdf at all, just garbage bytes")

    assert text == ""


def test_prefer_layout_uses_pdfplumber_directly():
    text_default = extract_text(HDB_TEMPLATE)
    text_layout = extract_text(HDB_TEMPLATE, prefer_layout=True)

    # 两种策略都该有实质内容
    assert len(text_default) > 1000
    assert len(text_layout) > 1000


@pytest.mark.parametrize(
    "pdf_name",
    [
        "Tenancy Agreement Template for HDB Flats.pdf",
        "Tenancy Agreement Template for Private Residential Property.pdf",
        "Form 4 - Estate Agency Agreement for the Lease of Residential Property by a Tenant.pdf",
        "Form 8 - Exclusive Estate Agency Agreement for the Lease of Residential Property by a Tenant.pdf",
    ],
)
def test_all_cea_templates_extract_successfully(pdf_name: str):
    pdf_path = DATA_DIR / pdf_name
    text = extract_text(pdf_path)

    assert len(text) > 500, f"{pdf_name} should extract non-trivial text"
