"""Alembic 环境配置

设计原则：
- 复用 src.infra.config 作为唯一配置入口
- DB URL 转换也在 src.infra.config 统一处理
- 不重复 load_dotenv、不重复解析 .env 路径
"""
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool
from alembic import context

# ===== 1. 让 alembic 能 import 到 src.* =====
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# ===== 2. Alembic Config =====
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ===== 3. 用项目统一的 Settings (URL 转换逻辑由 config.py 提供) =====
from src.infra.config import get_sync_database_url

config.set_main_option("sqlalchemy.url", get_sync_database_url())

# ===== 4. 导入 Base + 所有 model =====
from src.models.base import Base
import src.models  # noqa: F401  ← 触发 src/models/__init__.py

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """无 DB 连接时跑 migration（生成 SQL 脚本用）"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """有 DB 连接时跑 migration（正常用）"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,            # 比对列类型
            compare_server_default=True,  # 比对默认值
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()