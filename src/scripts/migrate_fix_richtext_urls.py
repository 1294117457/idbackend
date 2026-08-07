"""一次性迁移脚本：修复 template.description 中误存的预签名 URL

问题：process_html 的正则缺少 /{bucket}/ 前缀，导致预签名 URL
     被原样存入数据库，过期后图片无法显示（403）。

本脚本扫描所有 template.description，将已存储的
  src="/{bucket}/editor/{path}?X-Amz-..."
转换为占位符格式
  src="editor://{path}"

同时处理 temp/ 路径：如果文件仍在 temp/ 下，
尝试迁移到 editor/{entity_type}/{entity_id}/ 最终路径。

用法：
  cd idbackend
  python -m src.scripts.migrate_fix_richtext_urls
"""
import asyncio
import os
import re
import sys

from sqlalchemy import select, update

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.infra.database import AsyncSessionLocal
from src.infra.config import get_settings
from src.infra.storage.minio_adapter import build_default_minio_adapter
from src.models.template import Template


async def main():
    settings = get_settings()
    bucket = settings.MINIO_BUCKET
    storage = build_default_minio_adapter()

    escaped_bucket = re.escape(bucket)
    pattern = re.compile(
        rf'(src=["\'])/{escaped_bucket}/editor/([^"\'?\s&]+)(?:\?[^"\']*?)?(["\'])',
        flags=re.IGNORECASE,
    )

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Template))
        templates = result.scalars().all()

        fixed = 0
        for tpl in templates:
            if not tpl.description:
                continue

            matches = list(pattern.finditer(tpl.description))
            if not matches:
                continue

            html = tpl.description
            seen: set[str] = set()

            for match in matches:
                path = match.group(2)
                if path in seen:
                    continue
                seen.add(path)

                if path.startswith("temp/"):
                    filename = path[5:]
                    src_key = f"editor/{path}"
                    dst_key = f"editor/template/{tpl.id}/{filename}"

                    ok = storage.copy_object(src_key, dst_key)
                    if ok:
                        print(f"  [迁移] {src_key} -> {dst_key}")
                        await storage.delete(src_key)
                    else:
                        print(f"  [警告] 复制失败（文件可能已迁移）: {src_key}")

                    placeholder = f"editor://template/{tpl.id}/{filename}"
                else:
                    placeholder = f"editor://{path}"

                replace_pat = re.compile(
                    rf'(src=["\'])/{escaped_bucket}/editor/{re.escape(path)}(?:\?[^"\']*?)?(["\'])',
                    flags=re.IGNORECASE,
                )
                html = replace_pat.sub(rf'\1{placeholder}\2', html)

            if html != tpl.description:
                tpl.description = html
                fixed += 1
                print(f"[修复] template id={tpl.id} name={tpl.name}")

        if fixed > 0:
            await db.commit()
            print(f"\n完成：共修复 {fixed} 个模板的富文本图片 URL")
        else:
            print("\n无需修复：所有模板的 description 均为正确的占位符格式")

    storage.close()


if __name__ == "__main__":
    asyncio.run(main())
