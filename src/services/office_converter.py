"""Office → PDF 转换器（基于 LibreOffice headless）

设计原则（docs/file/分层设计.md §1）：
- 只做一件事：bytes(office) → bytes(pdf)
- 不持有 DB / Storage 状态
- 临时文件走 tempfile.TemporaryDirectory()，转换结束自动清理
- soffice 不可用或转换失败时抛 OfficeConvertError（路由层捕获后 501/500）

典型调用链路：
    router /preview
        └─ service.get_preview_bytes(file_id)
            └─ service._maybe_convert_office(data, content_type)
                └─ office_converter.convert_office_to_pdf(data, filename)
                    └─ asyncio.subprocess.run(soffice ...)
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from src.infra.config import get_settings

logger = logging.getLogger(__name__)


# ────── 错误 ──────

class OfficeConvertError(Exception):
    """Office → PDF 转换失败（含 soffice 不可用、转换超时、产物异常）"""


# ────── 支持的 Office 类型 ──────
# 依据 https://wiki.documentfoundation.org/Faq/General/Supported_File_Formats

OFFICE_CONTENT_TYPES = frozenset({
    # Microsoft Office（现代）
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",         # .xlsx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation", # .pptx
    # Microsoft Office（旧）
    "application/msword",                          # .doc
    "application/vnd.ms-excel",                    # .xls
    "application/vnd.ms-powerpoint",               # .ppt
    # OpenDocument
    "application/vnd.oasis.opendocument.text",      # .odt
    "application/vnd.oasis.opendocument.spreadsheet",  # .ods
    "application/vnd.oasis.opendocument.presentation", # .odp
})


def is_office_content_type(content_type: Optional[str]) -> bool:
    """判断 MIME 是否属于 LibreOffice 可处理的 Office 类型"""
    if not content_type:
        return False
    return content_type.lower() in {ct.lower() for ct in OFFICE_CONTENT_TYPES}


# ────── soffice 可用性 ──────

def is_soffice_available() -> bool:
    """检测系统是否安装了 LibreOffice

    - 不抛异常
    - 用于运行时降级判断（如容器内未装 LibreOffice 时直接返 501，提示下载）
    """
    return shutil.which("soffice") is not None or shutil.which("libreoffice") is not None


def _resolve_soffice_bin() -> str:
    """返回实际可用的 soffice 路径（soffice 优先，libreoffice 兜底）"""
    for name in ("soffice", "libreoffice"):
        path = shutil.which(name)
        if path:
            return path
    raise OfficeConvertError("LibreOffice 未安装（找不到 soffice / libreoffice 命令）")


# ────── 转换主入口 ──────

async def convert_office_to_pdf(
    file_bytes: bytes,
    filename: str,
    *,
    timeout: Optional[int] = None,
) -> bytes:
    """异步把 Office bytes 转 PDF bytes

    Args:
        file_bytes: 原始 Office 文件字节
        filename:   原始文件名（用于推断扩展名，必须含扩展名，如 `证明材料.docx`）
        timeout:    转换超时（秒），None 时取 settings.OFFICE_CONVERT_TIMEOUT

    Returns:
        PDF 字节流

    Raises:
        OfficeConvertError: 转换失败（soffice 不可用、超时、产物异常、扩展名未知）
    """
    settings = get_settings()
    if not settings.OFFICE_CONVERT_ENABLED:
        raise OfficeConvertError("OFFICE_CONVERT_ENABLED=False，已禁用转换")

    soffice_bin = _resolve_soffice_bin()
    timeout_s = timeout or settings.OFFICE_CONVERT_TIMEOUT

    suffix = Path(filename).suffix.lower()
    if not suffix:
        raise OfficeConvertError(f"文件名缺少扩展名：{filename!r}")

    # 用 TemporaryDirectory 包整个生命周期：退出时自动清理 .docx 和 .pdf
    with tempfile.TemporaryDirectory(prefix="office_conv_") as tmpdir:
        tmp_path = Path(tmpdir)
        input_path = tmp_path / f"input{suffix}"
        input_path.write_bytes(file_bytes)

        # --headless：无 GUI；--convert-to pdf：输出 PDF；
        # --outdir：输出目录（与 input 同目录即可）
        # 注：soffice 会用 input 的 basename + .pdf 作为输出文件名
        proc = await asyncio.create_subprocess_exec(
            soffice_bin,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmp_path),
            str(input_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise OfficeConvertError(f"LibreOffice 转换超时（>{timeout_s}s）：{filename}")

        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace")[:500]
            raise OfficeConvertError(
                f"LibreOffice 转换失败（exit={proc.returncode}）：{filename}\n{err_msg}"
            )

        output_path = input_path.with_suffix(".pdf")
        if not output_path.exists():
            raise OfficeConvertError(
                f"LibreOffice 转换产物不存在：{output_path}\n"
                f"stdout: {stdout.decode('utf-8', errors='replace')[:300]}"
            )

        pdf_bytes = output_path.read_bytes()
        if len(pdf_bytes) == 0:
            raise OfficeConvertError("LibreOffice 转换产物为空 PDF")

        logger.info(
            "office→pdf ok: %s (%d bytes → %d bytes)",
            filename, len(file_bytes), len(pdf_bytes),
        )
        return pdf_bytes
