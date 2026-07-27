"""迁移脚本：删除 knowledge_embeddings，创建 embeddings

执行方式：
    python -m src.scripts.migrate_to_embeddings

依赖：
    pip install psycopg2-binary
"""
from sqlalchemy import text
from sqlalchemy import create_engine

from src.infra.config import get_sync_database_url


def main():
    db_url = get_sync_database_url()
    engine = create_engine(db_url, echo=True)

    print("=" * 60)
    print("开始迁移：删除 knowledge_embeddings，创建 embeddings")
    print("=" * 60)

    with engine.connect() as conn:
        # 1. 删除旧的 knowledge_embeddings 表
        print("\n[1/4] 删除 knowledge_embeddings 表...")
        result = conn.execute(text("SELECT tablename FROM pg_tables WHERE tablename = 'knowledge_embeddings'"))
        if result.fetchone():
            conn.execute(text("DROP TABLE IF EXISTS knowledge_embeddings CASCADE"))
            conn.commit()
            print("    ✓ knowledge_embeddings 表已删除")
        else:
            print("    ○ knowledge_embeddings 表不存在，跳过")

        # 2. 创建新的 embeddings 表
        print("\n[2/4] 创建 embeddings 表...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS embeddings (
                id SERIAL PRIMARY KEY,
                title VARCHAR(200),
                content TEXT NOT NULL,
                category VARCHAR(50) NOT NULL,
                ref_id INTEGER,
                embedding JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.commit()
        print("    ✓ embeddings 表已创建")

        # 3. 创建索引
        print("\n[3/4] 创建索引...")
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_embeddings_category ON embeddings(category)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_embeddings_ref_id ON embeddings(ref_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_embeddings_category_ref_id ON embeddings(category, ref_id)"))
        conn.commit()
        print("    ✓ 索引已创建")

        # 4. 添加注释
        print("\n[4/4] 添加表注释...")
        conn.execute(text("COMMENT ON TABLE embeddings IS '统一向量表，用于 RAG 检索'"))
        conn.execute(text("COMMENT ON COLUMN embeddings.title IS '标题（方便人类识别）'"))
        conn.execute(text("COMMENT ON COLUMN embeddings.content IS '内容原文（检索后展示用）'"))
        conn.execute(text("COMMENT ON COLUMN embeddings.category IS '业务类型：POLICY / SYSTEM_GUIDE / TEMPLATE'"))
        conn.execute(text("COMMENT ON COLUMN embeddings.ref_id IS '关联业务 ID（如 template.id）'"))
        conn.execute(text("COMMENT ON COLUMN embeddings.embedding IS '1024 维 embedding 向量（JSON 数组存储）'"))
        conn.commit()
        print("    ✓ 注释已添加")

    print("\n" + "=" * 60)
    print("迁移完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
