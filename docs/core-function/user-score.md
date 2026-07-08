# 学生成绩体系实施指南（v1.0）

> **配套文档**：[四层职责设计 § 4-5](./四层职责设计.md) / [score_data 实施指南](./score_data.md)
>
> 本指南给出学生成绩体系的**实施层面**细节：数据库清理、账户信息接口、成绩计算算法。

---

## 一、数据库清理

### 1.1 users 表无用字段删除

**当前要删除的字段：**

| 字段名 | 类型 | 原因 |
|--------|------|------|
| `gpa` | double precision | 旧 GPA 字段，已由 score_info 替代 |
| `is_confirmed` | boolean | 旧确认状态字段，已废弃 |
| `demand_value` | json | 旧需求字段，已废弃 |
| `demand_files` | json | 旧需求文件字段，已废弃 |
| `academic_score` | double precision | 旧学业成绩，已由 score_info 替代 |
| `specialty_score` | double precision | 旧专长成绩，已由 score_info 替代 |
| `comprehensive_score` | double precision | 旧综合成绩，已由 score_info 替代 |
| `student_id` | character varying(50) | 学号从 username 提取，不再单独存储 |

**保留的字段：**

```sql
username, password, phone, avatar, status, last_login_at,
full_name, grade, graduation_year, enrollment_year, major,
id, created_at, updated_at, score_info jsonb, extra_info jsonb
```

**Migration SQL：**

```sql
ALTER TABLE users
  DROP COLUMN IF EXISTS gpa,
  DROP COLUMN IF EXISTS is_confirmed,
  DROP COLUMN IF EXISTS demand_value,
  DROP COLUMN IF EXISTS demand_files,
  DROP COLUMN IF EXISTS academic_score,
  DROP COLUMN IF EXISTS specialty_score,
  DROP COLUMN IF EXISTS comprehensive_score,
  DROP COLUMN IF EXISTS student_id;
```

### 1.2 学号提取规则

学号从 `username` 字段提取：

| username | student_id |
|----------|------------|
| `33120202201909@stu.xmu.edu.cn` | `33120202201909` |
| `33120202201910@stu.xmu.edu.cn` | `33120202201910` |
| `admin@xmu.edu.cn` | 无（管理员账户） |

**提取逻辑：**
```python
def extract_student_id(username: str) -> str | None:
    """从 username 提取学号"""
    if '@' in username:
        prefix = username.split('@')[0]
        # 学号格式：纯数字组成
        if prefix.isdigit():
            return prefix
    return None  # 管理员账户等
```

---

## 二、账户信息接口

### 2.1 接口列表

| 方法 | 路由 | 说明 |
|------|------|------|
| GET | `/api/users/me` | 获取当前用户账户信息 |
| PUT | `/api/users/me` | 更新当前用户账户信息 |

### 2.2 GET /api/users/me

**说明**：获取当前登录用户的完整账户信息。

**权限**：登录用户（学生 / 管理员）

**Response 200：**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": 1,
    "student_id": "33120202201909",
    "username": "33120202201909@stu.xmu.edu.cn",
    "full_name": "张三",
    "phone": "13800138000",
    "avatar": "https://example.com/avatar.jpg",
    "grade": 3,
    "enrollment_year": 2022,
    "graduation_year": 2026,
    "major": "计算机科学与技术"
  }
}
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | 用户 ID |
| `student_id` | string | 学号，从 username @ 前缀提取 |
| `username` | string | 完整用户名（邮箱格式） |
| `full_name` | string | 姓名 |
| `phone` | string | 手机号 |
| `avatar` | string | 头像 URL |
| `grade` | int | 当前年级 |
| `enrollment_year` | int | 入学年份 |
| `graduation_year` | int | 毕业年份 |
| `major` | string | 专业 |

### 2.3 PUT /api/users/me

**说明**：更新当前登录用户的账户信息。

**权限**：登录用户（学生 / 管理员）

**Request：**

```json
{
  "phone": "13800138000",
  "full_name": "张三",
  "avatar": "https://example.com/avatar.jpg",
  "grade": 3,
  "enrollment_year": 2022,
  "graduation_year": 2026,
  "major": "计算机科学与技术"
}
```

**不可修改字段（后端校验）：**

- `username` - 由注册时绑定，不可修改
- `student_id` - 从 username 提取，不支持修改
- `id` - 主键，不可修改
- `score_info` - 由 recalculate 自动写入，不支持手动修改

**Response 200：**

```json
{
  "code": 0,
  "message": "更新成功",
  "data": null
}
```

**Response 400（无效字段）：**

```json
{
  "code": 400,
  "message": "不允许修改 username 字段",
  "data": null
}
```

### 2.4 Service 层设计

```python
class UserProfileService:
    """用户账户信息服务"""

    @staticmethod
    async def get_profile(user_id: int) -> dict:
        """
        获取用户账户信息
        
        - 从 users 表读取基本信息
        - student_id 从 username 提取
        """
        user = await db.fetch_one(
            "SELECT id, username, full_name, phone, avatar, grade, "
            "enrollment_year, graduation_year, major "
            "FROM users WHERE id = :id",
            id=user_id
        )
        user["student_id"] = extract_student_id(user["username"])
        return user

    @staticmethod
    async def update_profile(user_id: int, data: dict) -> None:
        """
        更新用户账户信息
        
        - 过滤不可修改字段
        - 只更新允许的字段
        """
        forbidden = {"id", "username", "student_id", "score_info", 
                     "password", "status", "created_at", "updated_at"}
        update_data = {k: v for k, v in data.items() if k not in forbidden}
        
        if not update_data:
            return
        
        set_clause = ", ".join(f"{k} = :{k}" for k in update_data.keys())
        update_data["id"] = user_id
        
        await db.execute(
            f"UPDATE users SET {set_clause}, updated_at = NOW() WHERE id = :id",
            update_data
        )
```

---

## 三、成绩计算接口

### 3.1 接口列表

| 方法 | 路由 | 说明 |
|------|------|------|
| GET | `/api/score/me` | 获取我的成绩（读取 score_info） |
| POST | `/api/score/recalculate` | 手动重新计算成绩 |

### 3.2 GET /api/score/me

**说明**：获取当前学生的成绩信息。

**权限**：登录学生

**逻辑**：

1. 从 `user.score_info` 读取
2. 如果为空或未计算，触发一次 recalculate
3. 返回计算结果

**Response 200：**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "calculated_at": "2026-07-08T17:00:00+08:00",
    "categories": {
      "1": {"name": "加分总计", "score": 60.0, "max": 100.0},
      "2": {"name": "加分", "score": 60.0, "max": 80.0},
      "3": {"name": "学业加分", "score": 30.0, "max": 60.0},
      "4": {"name": "竞赛奖项", "score": 20.0, "max": 20.0},
      "5": {"name": "学术论文", "score": 10.0, "max": 10.0},
      "6": {"name": "专长加分", "score": 30.0, "max": 30.0},
      "7": {"name": "体育", "score": 30.0, "max": 30.0}
    },
    "total": 60.0
  }
}
```

### 3.3 POST /api/score/recalculate

**说明**：手动重新计算当前学生的成绩。

**权限**：登录学生

**触发场景**：

- 学生点击"计算我的成绩"按钮
- Application 通过后查看最新成绩

**Response 200：**

```json
{
  "code": 0,
  "message": "成绩已重新计算",
  "data": {
    "calculated_at": "2026-07-08T17:05:00+08:00",
    "categories": {...},
    "total": 60.0
  }
}
```

### 3.4 recalculate 算法详解

#### 3.4.1 算法流程（4 步）

```
Step 1: SQL 聚合叶子分类原始分
        SELECT category_id, SUM(score)
        FROM score_data
        WHERE user_id = :user_id AND is_active = TRUE
        GROUP BY category_id

Step 2: 内存中组装 template_category 树
        SELECT * FROM template_category WHERE is_active = TRUE
        按 parent_id 建树，O(n) 一次遍历

Step 3: 后序递归封顶
        叶子: capped = min(raw, category.max_score)
        非叶: capped = min(sum(子节点 capped), category.max_score)

Step 4: 收集所有节点得分（含非叶），覆盖写入 user.score_info
        UPDATE users SET score_info = :result WHERE id = :user_id
```

#### 3.4.2 示例树遍历

```
加分总计(max=100)
  └── 加分(max=80)
        ├── 学业加分(max=60)
        │     ├── 竞赛(raw=25, max=20)
        │     └── 论文(raw=15, max=10)
        └── 专长加分(max=30)
              └── 体育(raw=35, max=30)

执行顺序（后序遍历）：
  1. 竞赛 capped = min(25, 20) = 20
  2. 论文 capped = min(15, 10) = 10
  3. 学业加分 capped = min(20 + 10, 60) = 30
  4. 体育 capped = min(35, 30) = 30
  5. 专长加分 capped = min(30, 30) = 30
  6. 加分 capped = min(30 + 30, 80) = 60
  7. 加分总计 capped = min(60, 100) = 60
```

#### 3.4.3 伪代码实现

```python
async def recalculate(user_id: int, db) -> dict:
    """
    全量聚合 + 覆盖写 user.score_info，幂等可反复触发。
    
    返回: {
        "calculated_at": ISO datetime,
        "categories": {"<category_id>": {"name", "score", "max"}, ...},
        "total": float
    }
    """
    # Step 1: 获取叶子分类原始分
    raw_scores = await db.fetch_all("""
        SELECT category_id, SUM(score) as total
        FROM score_data 
        WHERE user_id = :uid AND is_active = TRUE
        GROUP BY category_id
    """, uid=user_id)
    leaf_scores = {r.category_id: float(r.total) for r in raw_scores}
    
    # Step 2: 构建分类树
    categories = await db.fetch_all("""
        SELECT id, parent_id, name, max_score
        FROM template_category 
        WHERE is_active = TRUE
    """)
    node_map = {c.id: c for c in categories}
    for c in categories:
        c.children = []
    for c in categories:
        if c.parent_id:
            node_map[c.parent_id].children.append(c)
    
    # Step 3: 后序递归封顶
    result = {}
    
    def calc(node):
        """计算单个节点得分（带封顶）"""
        if not node.children:  # 叶子节点
            raw = leaf_scores.get(node.id, 0.0)
            if node.max_score:
                return min(raw, float(node.max_score))
            return raw
        # 非叶子：子节点求和后再封顶
        children_sum = sum(calc(child) for child in node.children)
        if node.max_score:
            return min(children_sum, float(node.max_score))
        return children_sum
    
    def collect(node):
        """收集节点得分"""
        score = calc(node)
        result[str(node.id)] = {
            "name": node.name,
            "score": score,
            "max": float(node.max_score) if node.max_score else None
        }
        for child in node.children:
            collect(child)
    
    roots = [c for c in categories if not c.parent_id]
    for root in roots:
        collect(root)
    
    # Step 4: 写入 score_info
    total = 0.0
    if roots:
        total = result.get(str(roots[0].id), {}).get("score", 0.0)
    
    score_info = {
        "calculated_at": datetime.now().isoformat(),
        "categories": result,
        "total": total
    }
    
    await db.execute(
        "UPDATE users SET score_info = :info WHERE id = :uid",
        info=json.dumps(score_info),
        uid=user_id
    )
    
    return score_info
```

### 3.5 性能分析

| 操作 | 复杂度 | 说明 |
|------|--------|------|
| 获取 leaf_scores | O(n) | score_data 查询，n 为该学生记录数 |
| 构建分类树 | O(m) | m 为 active 分类数，通常 < 100 |
| 递归封顶 | O(m) | 后序遍历所有节点 |
| 更新 score_info | O(1) | 单行 UPDATE |

**结论**：整体 O(n + m)，单学生计算耗时 < 10ms。

---

## 四、score_data 失效处理

### 4.1 失效场景

当 Application 状态变为非 PASSED 时（如被撤销、被拒绝），对应的 score_data 不删除，只将 `is_active` 标记为 `FALSE`。

### 4.2 处理策略

**延迟重算** - 不主动修改 `user.score_info`，等学生下次点击"计算我的成绩"时再重新从 `score_data` 拉取有效记录计算。

| 事件 | 处理方式 |
|------|----------|
| Application PASSED | 写入 score_data，is_active=TRUE |
| Application REVOKED / REJECTED | 更新 score_data，is_active=FALSE |
| 学生点击"计算我的成绩" | recalculate 从 score_data 重新聚合 |

**优点**：

- 无需在 Application 状态变更时触发重算，避免事务复杂
- 学生可自行控制何时刷新成绩
- 延迟期间的 score_info 可能是"旧数据"，但不会丢失

**缺点**：

- 学生查看分数可能不是最新状态
- 需引导学生在必要时点击刷新

---

## 五、相关文件清单

```
src/
  models/
    user.py                    # User model（清理后）
    score_data.py              # ScoreData model
    template_category.py      # TemplateCategory model
  services/
    user_profile_service.py    # 账户信息服务（新增）
    score_data_service.py      # 成绩流水服务
    score_calculation_service.py # 成绩计算服务（新增/重构）
  routes/
    user.py                    # 账户信息路由（新增 GET/PUT /api/users/me）
    score.py                   # 成绩路由（GET/POST /api/score/*）
```

---

## 六、实施顺序

1. **Migration**：执行 SQLAlchemy 脚本清理 users 表无用字段
2. **Service**：实现 UserProfileService
3. **Route**：实现 `/api/users/me` GET/PUT
4. **Service**：实现 ScoreCalculationService.recalculate()
5. **Route**：实现 `/api/score/me` GET + `/api/score/recalculate` POST
6. **前端**：接入账户信息页面 + 成绩展示页面
7. **测试**：全流程联调

---

## 七、未决项

| 项 | 当前决策 | 备注 |
|----|----------|------|
| 管理员账户 username 无 @ | extract_student_id 返回 None | 前端不显示 student_id |
| recalculate 并发 | 不处理 | 学生量级小，单用户操作无并发 |
| score_data 失效后重算 | 延迟重算 | 学生点击"计算我的成绩"时触发 |
| 管理端修改个人信息 | 暂不考虑 | 后续直接去除管理端个人信息入口 |

---

## 八、数据库 Migration（SQLAlchemy）

```python
"""
Migration: 清理 users 表无用字段
执行: python -m migrations.clean_user_fields
"""
from sqlalchemy import text
from app.database import engine


def upgrade():
    """删除无用字段"""
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE users
              DROP COLUMN IF EXISTS gpa,
              DROP COLUMN IF EXISTS is_confirmed,
              DROP COLUMN IF EXISTS demand_value,
              DROP COLUMN IF EXISTS demand_files,
              DROP COLUMN IF EXISTS academic_score,
              DROP COLUMN IF EXISTS specialty_score,
              DROP COLUMN IF EXISTS comprehensive_score,
              DROP COLUMN IF EXISTS student_id
        """))
        print("✅ users 表无用字段已删除")


def downgrade():
    """回滚"""
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE users
              ADD COLUMN IF NOT EXISTS gpa DOUBLE PRECISION,
              ADD COLUMN IF NOT EXISTS is_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
              ADD COLUMN IF NOT EXISTS demand_value JSON,
              ADD COLUMN IF NOT EXISTS demand_files JSON,
              ADD COLUMN IF NOT EXISTS academic_score DOUBLE PRECISION NOT NULL DEFAULT 0,
              ADD COLUMN IF NOT EXISTS specialty_score DOUBLE PRECISION NOT NULL DEFAULT 0,
              ADD COLUMN IF NOT EXISTS comprehensive_score DOUBLE PRECISION NOT NULL DEFAULT 0,
              ADD COLUMN IF NOT EXISTS student_id VARCHAR(50)
        """))
        print("✅ 回滚完成")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "downgrade":
        downgrade()
    else:
        upgrade()
```

**保留的字段（清理后）：**

```sql
users (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(255) NOT NULL,       -- 邮箱格式，@前为学号
    password        VARCHAR(255) NOT NULL,
    phone           VARCHAR(15),
    avatar          VARCHAR(500),
    status          VARCHAR(20) NOT NULL,
    last_login_at   VARCHAR(50),
    full_name       VARCHAR(100),
    grade           INTEGER,
    graduation_year INTEGER,
    enrollment_year INTEGER,
    major           VARCHAR(100),
    created_at      TIMESTAMP NOT NULL,
    updated_at      TIMESTAMP NOT NULL,
    score_info      JSONB DEFAULT '{}',
    extra_info      JSONB DEFAULT '{}'
)
```
