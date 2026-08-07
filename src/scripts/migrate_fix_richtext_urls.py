"""一次性迁移脚本：修复 template.description 中误存的预签名 URL

问题：历史上 save_template 路径曾直接落库预签名 URL（不是占位符），
     过期后图片无法显示（403）。

本脚本扫描所有 template.description，将已存储的脏 URL 替换为占位符：
  src="/{bucket}/editor/{path}?X-Amz-..."  ->  src="editor://{path}"
  src="/editor/{path}?X-Amz-..."            ->  src="editor://{path}"

同时处理 temp/ 路径：如果文件仍在 temp/ 下，
尝试迁移到 editor/template/{template_id}/ 最终路径。

用法：
  cd idbackend
  # 预览（不写入）：
  python -m src.scripts.migrate_fix_richtext_urls --dry-run
  # 实际修复：
  python -m src.scripts.migrate_fix_richtext_urls
"""
import asyncio
import argparse
import os
import re
import sys

from sqlalchemy import select

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.infra.database import AsyncSessionLocal
from src.infra.config import get_settings
from src.infra.storage.minio_adapter import build_default_minio_adapter
from src.models.template import Template


async def main():
    parser = argparse.ArgumentParser(description="修复 template.description 中残留的预签名 URL")
    parser.add_argument("--dry-run", action="store_true", help="只扫描并打印，不修改数据库")
    args = parser.parse_args()

    settings = get_settings()
    bucket = settings.MINIO_BUCKET
    storage = build_default_minio_adapter()

    # 匹配三种格式：
    #   /{bucket}/editor/{path}?X-Amz-...
    #   /editor/{path}?X-Amz-...
    # 路径 group 2 截到 ? / " / ' / 空白为止
    escaped_bucket = re.escape(bucket)
    pattern = re.compile(
        rf'(src=["\'])(?:/{escaped_bucket})?/editor/([^"\'?\s&]+)(?:\?[^"\']*?)?(["\'])',
        flags=re.IGNORECASE,
    )

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Template))
        templates = result.scalars().all()

        fixed = 0
        scanned = 0
        for tpl in templates:
            if not tpl.description:
                continue
            scanned += 1

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

                    if not args.dry_run:
                        ok = storage.copy_object(src_key, dst_key)
                        if ok:
                            print(f"  [迁移] {src_key} -> {dst_key}")
                            await storage.delete(src_key)
                        else:
                            print(f"  [警告] 复制失败（文件可能已迁移）: {src_key}")

                    placeholder = f"editor://template/{tpl.id}/{filename}"
                else:
                    placeholder = f"editor://{path}"

                # 替换时仍然兼容两种格式（带/不带 bucket 前缀）
                replace_pat = re.compile(
                    rf'(src=["\'])(?:/{escaped_bucket})?/editor/{re.escape(path)}(?:\?[^"\']*?)?(["\'])',
                    flags=re.IGNORECASE,
                )
                html = replace_pat.sub(rf'\1{placeholder}\2', html)

            if html != tpl.description:
                tpl.description = html
                fixed += 1
                mode = "[预览-修复]" if args.dry_run else "[修复]"
                print(f"{mode} template id={tpl.id} name={tpl.name}")

        if args.dry_run:
            print(f"\n[DRY RUN] 扫描 {scanned} 个模板，预览 {fixed} 个需要修复（未写入）")
        elif fixed > 0:
            await db.commit()
            print(f"\n完成：共修复 {fixed} 个模板的富文本图片 URL")
        else:
            print("\n无需修复：所有模板的 description 均为正确的占位符格式")

    storage.close()


if __name__ == "__main__":
    asyncio.run(main())
