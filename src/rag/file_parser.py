"""文件解析"""
from typing import Optional


def parse_file_to_text(
    content: bytes,
    filename: str,
) -> str:
    """解析文件为文本"""
    ext = filename.lower().split(".")[-1] if "." in filename else ""

    if ext == "pdf":
        return parse_pdf(content)
    elif ext in ["doc", "docx"]:
        return parse_docx(content)
    elif ext in ["xls", "xlsx"]:
        return parse_xlsx(content)
    elif ext == "txt":
        return content.decode("utf-8", errors="ignore")
    else:
        return ""


def parse_pdf(content: bytes) -> str:
    """解析 PDF"""
    # TODO: 使用 pdfplumber
    return ""


def parse_docx(content: bytes) -> str:
    """解析 DOCX"""
    # TODO: 使用 mammoth
    return ""


def parse_xlsx(content: bytes) -> str:
    """解析 Excel"""
    # TODO: 使用 openpyxl
    return ""
