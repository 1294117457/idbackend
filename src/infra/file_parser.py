"""文件解析工具

策略：
- PDF → pdfplumber（轻量快速，不依赖 inference）
- 其他格式 → unstructured partition（统一处理）

支持格式：
- 文档类：PDF / DOCX / DOC / PPTX / PPT / RTF / ODT / EPUB
- 表格类：XLSX / XLS / CSV / TSV
- 文本类：TXT / MD / HTML / HTM / XML / JSON / RST / ORG
- 图片类（需 OCR）：PNG / JPG / JPEG / TIFF / BMP
"""
import io
import os
import tempfile
import logging

logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS = {
    "pdf", "docx", "doc", "pptx", "ppt", "rtf", "odt", "epub",
    "xlsx", "xls", "csv", "tsv",
    "txt", "md", "html", "htm", "xml", "json", "rst", "org",
    "png", "jpg", "jpeg", "tiff", "bmp",
}

# PDF 单独用 pdfplumber，不走 unstructured（避免 unstructured_inference 依赖）
_FAST_PARSERS = {
    "pdf": "_parse_pdf",
    "txt": "_parse_txt",
    "md": "_parse_txt",
}


def parse_file(file_bytes: bytes, filename: str) -> str:
    """解析文件为文本。

    Args:
        file_bytes: 文件字节内容
        filename: 文件名（用于判断类型）

    Returns:
        提取的文本内容，解析失败返回空字符串
    """
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if ext not in _SUPPORTED_EXTENSIONS:
        logger.warning(f"不支持的文件类型: {ext}, 文件名: {filename}")
        return ""

    # 优先用快速解析器（PDF / TXT）
    if ext in _FAST_PARSERS:
        try:
            parser = globals()[_FAST_PARSERS[ext]]
            result = parser(file_bytes)
            if result and result.strip():
                return result.strip()
        except Exception as e:
            logger.warning(f"快速解析失败 ({filename}): {e}，尝试 unstructured")

    # 其他格式走 unstructured
    return _parse_with_unstructured(file_bytes, filename, ext)


def get_supported_extensions() -> set[str]:
    return _SUPPORTED_EXTENSIONS.copy()


def is_supported(filename: str) -> bool:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    return ext in _SUPPORTED_EXTENSIONS


# ═══════════════════════════════════════════════════════════════════════════════
# 快速解析器
# ═══════════════════════════════════════════════════════════════════════════════


def _parse_pdf(file_bytes: bytes) -> str:
    """PDF 解析（pdfplumber）。"""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        texts = []
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                texts.append(text)
        return "\n".join(texts)


def _parse_txt(file_bytes: bytes) -> str:
    """纯文本解析（自动检测编码）。"""
    for enc in ("utf-8", "gbk", "gb2312", "big5", "latin-1"):
        try:
            return file_bytes.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return file_bytes.decode("utf-8", errors="ignore")


# ═══════════════════════════════════════════════════════════════════════════════
# unstructured 通用解析器
# ═══════════════════════════════════════════════════════════════════════════════


def _parse_with_unstructured(file_bytes: bytes, filename: str, ext: str) -> str:
    """使用 unstructured partition 解析。"""
    try:
        from unstructured.partition.auto import partition
    except ImportError:
        logger.error("unstructured 未安装，请执行: pip install 'unstructured[all-docs]'")
        return ""

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        elements = partition(filename=tmp_path)
        texts = [el.text for el in elements if hasattr(el, "text") and el.text]
        return "\n".join(texts)
    except Exception as e:
        logger.error(f"unstructured 解析失败 ({filename}): {e}")
        return ""
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
