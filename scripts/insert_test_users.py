#!/usr/bin/env python3
"""
批量插入50个用户测试数据的脚本
使用: python3 scripts/insert_test_users.py
"""

import sys
import os
from datetime import datetime, timedelta
import json
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from src.models.config import Base


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://zhouch:zhouchenhui@223.109.49.63:5432/iddata"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

MAJORS = [
    "计算机科学与技术", "软件工程", "人工智能", "数据科学与大数据技术",
    "网络工程", "信息安全", "物联网工程", "电子信息工程",
    "通信工程", "自动化", "机械工程", "材料科学与工程"
]

STATUSES = ["active", "inactive", "pending"]

FIRST_NAMES = ["张", "李", "王", "刘", "陈", "杨", "黄", "赵", "周", "吴",
               "徐", "孙", "马", "朱", "胡", "郭", "林", "何", "高", "罗"]
LAST_NAMES = ["伟", "芳", "娜", "敏", "静", "丽", "强", "磊", "军", "洋",
              "勇", "艳", "杰", "涛", "明", "超", "秀英", "华", "鑫", "宇"]


def random_name() -> str:
    return random.choice(FIRST_NAMES) + random.choice(LAST_NAMES)


def random_phone() -> str:
    return f"1{random.randint(3, 9)}{random.randint(100000000, 999999999)}"


def random_grade() -> int:
    return random.randint(2020, 2025)


def random_major() -> str:
    return random.choice(MAJORS)


def random_timestamp(days_back: int = 365) -> datetime:
    return datetime.now() - timedelta(
        days=random.randint(0, days_back),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59)
    )


def insert_test_users(count: int = 50):
    session = SessionLocal()
    now = datetime.now()

    try:
        existing_usernames = set(
            row[0] for row in session.execute(
                text("SELECT username FROM users")
            ).fetchall()
        )

        users_to_insert = []
        for i in range(count):
            username = f"test_user_{i+1:03d}"
            while username in existing_usernames:
                username = f"test_user_{i+1:03d}_{random.randint(1000, 9999)}"
            existing_usernames.add(username)

            created = random_timestamp(365)
            grade = random_grade()

            user = {
                "username": username,
                "password": "pbkdf2:sha256:260000$test$sha256hash1234567890abcdef",
                "phone": random_phone(),
                "avatar": f"https://api.dicebear.com/7.x/initials/svg?seed={username}",
                "status": random.choice(STATUSES),
                "last_login_at": (random_timestamp(30)).strftime("%Y-%m-%d %H:%M:%S"),
                "full_name": random_name(),
                "grade": grade,
                "graduation_year": grade + 4,
                "enrollment_year": grade,
                "major": random_major(),
                "score_info": json.dumps({"total": random.randint(0, 100), "rank": random.randint(1, 100)}),
                "extra_info": json.dumps({"bio": f"这是测试用户 {username}", "city": "北京"}),
                "created_at": created,
                "updated_at": now,
            }
            users_to_insert.append(user)

        session.execute(
            text("""
            INSERT INTO users (
                username, password, phone, avatar, status, last_login_at,
                full_name, grade, graduation_year, enrollment_year, major,
                score_info, extra_info, created_at, updated_at
            ) VALUES (
                :username, :password, :phone, :avatar, :status, :last_login_at,
                :full_name, :grade, :graduation_year, :enrollment_year, :major,
                :score_info, :extra_info, :created_at, :updated_at
            )
            """),
            users_to_insert
        )
        session.commit()
        print(f"✓ 成功插入 {count} 个测试用户")
        return True

    except Exception as e:
        session.rollback()
        print(f"✗ 插入失败: {e}")
        return False
    finally:
        session.close()


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    success = insert_test_users(count)
    sys.exit(0 if success else 1)
