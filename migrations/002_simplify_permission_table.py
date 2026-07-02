"""迁移脚本：简化权限表结构

此迁移脚本将：
1. 重命名 permission_code -> code
2. 重命名 permission_name -> name
3. 移除 module, is_menu, icon, component_path 字段
4. 确保 route_path 存在（已有）

执行前请备份数据库！
"""

import sys
sys.path.insert(0, '.')

from sqlalchemy import text
from src.core.database import engine, SessionLocal


def migrate():
    """执行迁移"""
    print("🚀 开始权限表结构迁移...")
    
    with engine.connect() as conn:
        # 1. 检查原始表是否存在
        result = conn.execute(text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'permission')"))
        if not result.scalar():
            print("❌ 权限表不存在，请先运行初始化")
            return False
        
        # 2. 重命名字段
        print("📝 重命名字段...")
        
        # 检查旧字段是否存在
        check_columns = conn.execute(text("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'permission'
        """))
        columns = [row[0] for row in check_columns.fetchall()]
        
        print(f"   当前字段: {columns}")
        
        # 重命名 permission_code -> code
        if 'permission_code' in columns:
            conn.execute(text('ALTER TABLE permission RENAME COLUMN permission_code TO code'))
            print("   ✅ permission_code -> code")
        
        # 重命名 permission_name -> name
        if 'permission_name' in columns:
            conn.execute(text('ALTER TABLE permission RENAME COLUMN permission_name TO name'))
            print("   ✅ permission_name -> name")
        
        # 3. 删除不需要的字段
        print("🗑️  删除不需要的字段...")
        fields_to_remove = ['module', 'is_menu', 'icon', 'component_path']
        for field in fields_to_remove:
            if field in columns:
                try:
                    conn.execute(text(f'ALTER TABLE permission DROP COLUMN IF EXISTS {field}'))
                    print(f"   ✅ 删除字段: {field}")
                except Exception as e:
                    print(f"   ⚠️ 删除 {field} 失败: {e}")
        
        conn.commit()
        
        # 4. 验证新结构
        print("\n📋 验证新结构...")
        check_new = conn.execute(text("""
            SELECT column_name, data_type FROM information_schema.columns 
            WHERE table_name = 'permission'
            ORDER BY ordinal_position
        """))
        print("   字段列表:")
        for row in check_new.fetchall():
            print(f"   - {row[0]} ({row[1]})")
        
        print("\n✅ 迁移完成！")
        return True


def rollback():
    """回滚迁移（撤销重命名）"""
    print("🔄 回滚迁移...")
    
    with engine.connect() as conn:
        # 重命名回来
        conn.execute(text('ALTER TABLE permission RENAME COLUMN code TO permission_code'))
        conn.execute(text('ALTER TABLE permission RENAME COLUMN name TO permission_name'))
        
        # 重新添加字段（需要默认值）
        conn.execute(text('ALTER TABLE permission ADD COLUMN IF NOT EXISTS module VARCHAR(50) NOT NULL DEFAULT \'default\''))
        conn.execute(text('ALTER TABLE permission ADD COLUMN IF NOT EXISTS is_menu BOOLEAN DEFAULT FALSE'))
        conn.execute(text('ALTER TABLE permission ADD COLUMN IF NOT EXISTS icon VARCHAR(100)'))
        conn.execute(text('ALTER TABLE permission ADD COLUMN IF NOT EXISTS component_path VARCHAR(255)'))
        
        conn.commit()
        print("✅ 回滚完成")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--rollback', action='store_true', help='回滚迁移')
    args = parser.parse_args()
    
    if args.rollback:
        rollback()
    else:
        migrate()
