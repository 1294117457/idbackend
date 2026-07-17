# 学生成绩体系实施指南（v1.1）

> **配套文档**：[四层职责设计 § 4-5](./四层职责设计.md) / [score_data 实施指南](./score_data.md)
>
> 本指南给出学生成绩体系的**实施层面**细节：数据库清理、账户信息接口、成绩计算算法、学生前端展示。

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

---

## 九、我的成绩 - 学生前端展示（v1.1 新增）

> 本章基于第一章的 recalculate 算法 + score_data 流水，定义学生端"我的成绩"卡片的渲染规范与后端 `recalculate` 返回结构升级。
>
> **核心目标**：
> - 后台 `template_category` 树可动态调整（增删改节点、改 max_score、停用分类）—— 学生下次刷新成绩后视图自动适配
> - 卡片内直接渲染分类树 + 节点封顶分数；点击叶子节点在卡片下方**嵌套展示**该叶子下的 PASSED application 列表
> - 停用分类（`is_active = FALSE`）不在学生端出现

### 9.1 设计原则

1. **以 `score_info` 为唯一前端数据源**——recalculate 后写入 DB，前端 GET `/api/score/me` 读取，禁止前端自己 GROUP BY `score_data` 重新聚合
2. **封顶逻辑只在后端**——`recalculate` 算好封顶前后两个数（`raw` / `score`），前端只负责展示，不做二次封顶
3. **application 列表随 `tree` 一次返回**——recalculate 阶段多一条 SQL 拉该用户 `score_data` 行，按 `category_id` 分组塞到对应叶子节点，前端无需再为列表发请求
4. **节点是 N-ary 树，不限层级**——渲染用扁平列表 + paddingLeft 缩进模拟树形（不用 el-tree 组件，避免点击行为与嵌套 card 展开冲突）
5. **叶子节点标识**——`is_bind_template = TRUE` 的分类是叶子，只有叶子节点才持有 `applications` 列表与"展开"按钮

### 9.2 后端：`recalculate` / `get_summary` 返回结构升级

#### 9.2.1 新返回结构

```jsonc
{
  "calculated_at": "2026-07-08T17:05:00+08:00",
  "total": 60.0,                   // 根节点封顶后分数；多根时为各根 score 之和
  "tree": [                         // 多根数组；空 [] 表示暂无任何激活分类
    {
      "id": 1,
      "name": "加分总计",
      "max": 100.0,                 // 该分类 max_score（封顶上限）
      "score": 60.0,                // 封顶后分数
      "raw": 80.0,                  // 封顶前原始分（仅展示用，给学生看"超额"幅度）
      "depth": 0,                   // 根到当前节点的层级（preorder 累加，根=0）
      "isLeaf": false,              // is_bind_template：true=叶子，false=非叶子
      "applications": [],           // 非叶子恒为 []
      "children": [
        {
          "id": 3, "name": "学业加分", "max": 60.0,
          "score": 30.0, "raw": 40.0, "depth": 2,
          "isLeaf": false, "applications": [],
          "children": [
            {
              "id": 5, "name": "竞赛奖项", "max": 20.0,
              "score": 20.0, "raw": 25.0, "depth": 3,
              "isLeaf": true,
              "applications": [     // 仅叶子节点非空
                {
                  "id": 101,                  // application.id
                  "name": "ACM亚洲区域赛",      // score_data.name 快照
                  "score": 10.0,               // 该条流水分数
                  "created_at": "2026-07-01T10:00:00+08:00"
                },
                { "id": 102, "name": "数学建模国赛", "score": 5.0,  "created_at": "..." },
                { "id": 103, "name": "蓝桥杯省一",   "score": 5.0,  "created_at": "..." }
              ],
              "children": []                  // 叶子恒为 []
            }
          ]
        }
      ]
    }
  ]
}
```

#### 9.2.2 算法追加步骤（在原有 § 3.4 基础上扩展）

原 recalculate 4 步算法扩展到 **5 步**：

```
Step 1: 同 SQL 聚合叶子分类原始分
        SELECT category_id, SUM(score)
        FROM score_data WHERE user_id=? AND is_active=TRUE GROUP BY category_id

Step 2: 同 SQL 拉所有激活分类 + 内存建树

Step 3: 同后序递归封顶，得 result dict 和 categories 计算结果

Step 4: 收集节点时同时计算 depth（preorder 累加）：
        - children=[] 且 result 中无 children 字段 → 标记 isLeaf = is_bind_template
        - 此时持有 raw（封顶前）和 score（封顶后）

Step 5（新增）：多一条 SQL 拉该用户所有 is_active=TRUE 的 score_data 流水，
                按 category_id 分组装进叶子节点：
        SELECT application_id, category_id, name, score, created_at
        FROM score_data
        WHERE user_id=:uid AND is_active=TRUE
        ORDER BY category_id, created_at DESC

Step 6（结构调整）：把 result 转为树形结构 + 顶层包成
        {
          "calculated_at": ISO datetime,
          "total": <根节点封顶后 score 之和，多根求和>,
          "tree": [root1, root2, ...]
        }

Step 7: 原覆盖写入 score_info 的逻辑不变（DB 仍存 flat 结构以便其他接口复用）；
        新的 tree 字段**不写 DB**——只作为接口返回的派生字段
```

**为什么 tree 不写 DB**：前端一次请求用即可；存在 DB 里反而要处理"分类树改了 → 老 tree 数据不一致"的清理逻辑。recalculate 是幂等的，每次调用都会重新组装。

#### 9.2.3 代码实现要点（伪代码）

```python
async def recalculate(db, user_id: int) -> dict:
    # Step 1-3 不变：拿 leaf_scores，构建分类树，后序封顶
    # Step 4：把 flat result + 节点元数据组合成带元信息的 dict
    node_info = {}   # {category_id: {name, max, score, raw, depth, isLeaf}}
    flat_score = {}  # 原有 result 别名，下方 compute 用

    def compute(node, depth):
        # 用原 calc(node, leaf_scores) 算 score
        raw = _raw_sum(node, leaf_scores)       # 封顶前
        score = calc(node, leaf_scores)          # 封顶后
        node_info[str(node.id)] = {
            "name": node.name,
            "max": float(node.max_score),
            "score": score,
            "raw": raw,
            "depth": depth,
            "isLeaf": node.is_bind_template,
        }
        for child in sorted(node.children, key=lambda c: (c.sort_order, c.id)):
            compute(child, depth + 1)

    def _raw_sum(node, leaf_scores):
        if not node.children:
            return leaf_scores.get(node.id, 0.0)
        return sum(_raw_sum(c, leaf_scores) for c in node.children)

    # Step 5：拉 application 列表
    app_rows = await db.execute(text("""
        SELECT application_id, category_id, name, score, created_at
        FROM score_data
        WHERE user_id = :uid AND is_active = TRUE
        ORDER BY category_id, created_at DESC
    """), {"uid": user_id})
    apps_by_cat = defaultdict(list)
    for r in app_rows:
        apps_by_cat[r.category_id].append({
            "id": r.application_id,
            "name": r.name,
            "score": float(r.score),
            "created_at": r.created_at.isoformat(),
        })

    # Step 6：组装树形结构
    def build(node, depth):
        info = node_info[str(node.id)]
        children_list = []
        for child in sorted(node.children, key=lambda c: (c.sort_order, c.id)):
            children_list.append(build(child, depth + 1))
        return {
            "id": node.id,
            "name": info["name"],
            "max": info["max"],
            "score": info["score"],
            "raw": info["raw"],
            "depth": info["depth"],
            "isLeaf": info["isLeaf"],
            "applications": apps_by_cat.get(node.id, []) if info["isLeaf"] else [],
            "children": children_list,
        }

    all_categories = (await db.execute(text(
        "SELECT * FROM template_category WHERE is_active = TRUE ORDER BY parent_id NULLS FIRST, sort_order, id"
    ))).fetchall()
    # ... 按原逻辑建 N-ary 树，root=parent_id IS NULL 的节点
    tree = []
    for root in roots:
        # 先 compute(root, 0) 把整棵子树填充到 node_info
        compute(root, 0)
        tree.append(build(root, 0))

    total = sum(t["score"] for t in tree)

    response = {
        "calculated_at": datetime.now().isoformat(),
        "total": total,
        "tree": tree,
    }

    # Step 7：DB 仍存 flat 结构（兼容其他接口），新 tree 字段只作为返回
    flat = _flatten_for_db(node_info)   # 原 result dict 形态
    await db.execute(
        "UPDATE users SET score_info = :info WHERE id = :uid",
        {"info": json.dumps({
            "calculated_at": response["calculated_at"],
            "categories": flat,
            "total": total,
        }), "uid": user_id}
    )
    return response
```

**SQL 总量**：5 条（4 原有 + 1 新增 application 列表）。仍然是 O(1)，无 N+1。

**`get_summary` 同步升级**：调用 recalculate 后直接把 `response` 返回前端，不再单独写 flat dict。

### 9.3 路由变化

| Method | Path | 行为 |
|---|---|---|
| `GET  /api/score/me`        | 调 `get_summary` → 返回新 `tree` 结构 |
| `POST /api/score/recalculate` | 调 `recalculate` → 返回新 `tree` 结构 |

其他（`/api/score/recalculate-all` 管理端、`/api/score/recalculate-by-admin` 管理端）仍返回旧 flat 结构，不影响管理端。

### 9.4 前端：profile 页面新加 card

#### 9.4.1 布局

```
┌─ 我的成绩 ─────────────────────────[刷新成绩]┐
│                                            │
│         60.0                                │
│         / 100      总加分上限               │
│                                            │
│  上次计算：2026-07-08 17:05                 │
│  ─────────────────────────────────────     │
│                                            │
│  加分总计            ██████░░ 60.0 / 100    │
│    加分              ██████░░ 60.0 / 80     │
│      学业加分        ████░░░░ 30.0 / 60     │
│        竞赛奖项      ████████ 20.0 / 20  [3 项]│  ← 叶子节点，右侧按钮点击展开
│      ┌────────────────────────────────────┐│
│      │「竞赛奖项」下的申请（共 3 项）      ││   ← 嵌套 card（仅叶子）
│      │ ACM亚洲区域赛        10.0  07-01   ││
│      │ 数学建模国赛          5.0  06-15   ││
│      │ 蓝桥杯省一            5.0  05-22   ││
│      │                [查看详情 →]        ││
│      └────────────────────────────────────┘│
│        学术论文        ████████ 10.0 / 10    │
│      专长加分          ████████ 30.0 / 30    │
│        体育            ████░░░░ 30.0 / 30    │
└────────────────────────────────────────────┘
```

#### 9.4.2 关键交互

| 节点类型 | 渲染 | 可点击行为 |
|---|---|---|
| **根节点**（depth=0, isLeaf=false） | 行 + 进度条 + score/max | 无（仅展示） |
| **中间节点**（isLeaf=false） | 行 + 进度条 + score/max；raw > max 时加 "超额 X" tag | 无 |
| **叶子节点**（isLeaf=true, applications=[]） | 行 + 进度条 + 0/max | 无（无展开按钮） |
| **叶子节点**（isLeaf=true, applications.length > 0） | 行 + 进度条 + score/max + 右侧 `N 项` 按钮 | 点按钮 → 在行下方展开嵌套 card |

**展开语义**：
- `expandedCategoryId: number | null` 单值——同时只展开 1 个叶子节点
- 点同一个叶子按钮 → 折叠（toggle）
- 嵌套 card 内 `el-table` 列：`name` / `score` / `通过时间` / 操作（"详情" → 跳 `/application/{id}`）

#### 9.4.3 示例代码（Vue 3 + Element Plus）

```vue
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { getMyScore, recalculateScore } from '@/api/components/apiScore'

interface ScoreApplication {
  id: number
  name: string
  score: number
  created_at: string
}

interface ScoreTreeNode {
  id: number
  name: string
  max: number
  score: number
  raw: number
  depth: number
  isLeaf: boolean
  applications: ScoreApplication[]
  children: ScoreTreeNode[]
}

interface ScoreTreeResponse {
  calculated_at: string
  total: number
  tree: ScoreTreeNode[]
}

// 用深度优先把树拍扁成渲染数组
function flattenTree(nodes: ScoreTreeNode[]): ScoreTreeNode[] {
  const out: ScoreTreeNode[] = []
  const walk = (ns: ScoreTreeNode[]) => {
    for (const n of ns) {
      out.push(n)
      if (n.children?.length) walk(n.children)
    }
  }
  walk(nodes)
  return out
}

const loading = ref(true)
const recalculating = ref(false)
const scoreInfo = ref<ScoreTreeResponse | null>(null)
const expandedCategoryId = ref<number | null>(null)

const flatRows = computed(() =>
  scoreInfo.value ? flattenTree(scoreInfo.value.tree) : []
)
const totalDisplay = computed(() => scoreInfo.value?.total ?? 0)
const rootMax = computed(() => {
  if (!scoreInfo.value?.tree?.length) return 0
  return scoreInfo.value.tree.reduce((s, n) => s + n.max, 0)
})
const formattedCalculatedAt = computed(() => {
  if (!scoreInfo.value?.calculated_at) return ''
  return new Date(scoreInfo.value.calculated_at).toLocaleString('zh-CN')
})

const fetchScore = async () => {
  loading.value = true
  try {
    const res = await getMyScore()
    scoreInfo.value = res.data
  } finally {
    loading.value = false
  }
}

const handleRecalculate = async () => {
  recalculating.value = true
  try {
    const res = await recalculateScore()
    scoreInfo.value = res.data
    ElMessage.success('成绩已重新计算')
  } finally {
    recalculating.value = false
  }
}

const toggleExpand = (node: ScoreTreeNode) => {
  if (!node.isLeaf || !node.applications.length) return
  expandedCategoryId.value = expandedCategoryId.value === node.id ? null : node.id
}

const formatTime = (iso: string) => new Date(iso).toLocaleString('zh-CN')

const goApplicationDetail = (id: number) => {
  // 跳转到申请详情页（已存在的 ApplyHistory 或 application 详情）
  window.location.href = `/application/${id}`
}

onMounted(fetchScore)
</script>

<template>
  <el-card>
    <template #header>
      <div class="flex items-center justify-between">
        <h4 class="page-title">我的成绩</h4>
        <el-button
          type="primary"
          :loading="recalculating"
          @click="handleRecalculate"
        >
          <el-icon class="mr-1"><Refresh /></el-icon>
          {{ scoreInfo ? '刷新成绩' : '计算成绩' }}
        </el-button>
      </div>
    </template>

    <div v-if="loading" class="flex justify-center py-10">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
    </div>

    <!-- 空状态 -->
    <div v-else-if="!scoreInfo?.tree?.length" class="text-center py-10 text-gray-500">
      <p>暂无激活分类</p>
      <p class="text-xs mt-1">管理员尚未配置分类树</p>
    </div>

    <template v-else>
      <!-- 总分大字 -->
      <div class="text-center mb-6">
        <div class="text-5xl font-bold text-primary">
          {{ totalDisplay.toFixed(1) }}
        </div>
        <div class="text-sm text-gray-500 mt-1">
          / {{ rootMax.toFixed(1) }} 总加分上限
        </div>
        <div v-if="formattedCalculatedAt" class="text-xs text-gray-400 mt-2">
          上次计算：{{ formattedCalculatedAt }}
        </div>
      </div>

      <!-- 扁平化行渲染 + 叶子行下方展开嵌套 card -->
      <template v-for="node in flatRows" :key="node.id">
        <div
          class="flex items-center gap-3 py-2 hover:bg-gray-50 cursor-pointer"
          :class="{ 'cursor-default': !node.isLeaf || !node.applications.length }"
          :style="{ paddingLeft: (node.depth * 24 + 12) + 'px' }"
          @click="toggleExpand(node)"
        >
          <span class="font-medium min-w-[120px]">{{ node.name }}</span>
          <el-tag
            v-if="node.raw > node.max"
            size="small"
            type="warning"
            class="ml-1"
          >
            超额 {{ (node.raw - node.max).toFixed(1) }}
          </el-tag>
          <el-progress
            :percentage="Math.min(100, (node.score / node.max) * 100)"
            :stroke-width="6"
            class="flex-1"
            :show-text="false"
          />
          <span class="font-mono text-sm w-24 text-right">
            {{ node.score.toFixed(1) }} / {{ node.max.toFixed(1) }}
          </span>
          <el-button
            v-if="node.isLeaf && node.applications.length"
            link
            type="primary"
            size="small"
            @click.stop="toggleExpand(node)"
          >
            {{ expandedCategoryId === node.id ? '收起' : node.applications.length + ' 项' }}
          </el-button>
        </div>

        <!-- 叶子展开：嵌套 card -->
        <div
          v-if="expandedCategoryId === node.id && node.applications.length"
          class="mb-3"
          :style="{ marginLeft: (node.depth * 24 + 36) + 'px' }"
        >
          <el-card shadow="never" class="bg-gray-50">
            <template #header>
              <span class="text-sm">
                「{{ node.name }}」下的申请（共 {{ node.applications.length }} 项）
              </span>
            </template>
            <el-table :data="node.applications" size="small">
              <el-table-column prop="name" label="项目" />
              <el-table-column
                prop="score"
                label="得分"
                width="80"
                align="right"
              />
              <el-table-column label="通过时间" width="180">
                <template #default="{ row }">
                  <span class="text-xs text-gray-500">
                    {{ formatTime(row.created_at) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="80" align="center">
                <template #default="{ row }">
                  <el-button
                    link
                    type="primary"
                    size="small"
                    @click="goApplicationDetail(row.id)"
                  >
                    详情
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </div>
      </template>
    </template>
  </el-card>
</template>
```

#### 9.4.4 状态管理

页面本地 `ref` 即可，不必上 Pinia——profile 页是单页独有数据。

**空态 vs 已有数据态切换**：
- 卡片右上按钮文案根据 `scoreInfo` 是否为空切换：
  - `null` → "计算成绩"（首次进入）
  - 已有 → "刷新成绩"
- 学生点完后立刻看到新数据，按钮回到 "刷新成绩"

### 9.5 政策变化适配矩阵

| 后台操作 | recalculate 行为 | 学生下次刷新后看到 |
|---|---|---|
| 改了某分类 `max_score` | 该节点 `max` 字段变更；封顶重新计算 | 节点 `score` 按新上限重新封顶；进度条比例变化 |
| 增了子分类 | 树多一个节点，depth 调整 | 树多一行（自动出现在父节点下） |
| 删了某叶子（无未关 application） | 节点消失；其历史 PASSED 申请 score_data 不参与聚合 | 树少一行 |
| 删了某中间节点（无未关 application，级联删子） | 该分支整段消失 | 学生可能在嵌套 card 里看不到原 application——但 score_data 行保留在 DB |
| `is_active = FALSE` 某分类 | recalculate 时 `WHERE is_active = TRUE` 过滤掉 | 该节点直接从树里消失；其他不受影响 |
| 启用（`FALSE → TRUE`） | 重新出现在树 | 学生下次刷新看到 |
| 改 `is_bind_template`（由 template 解绑触发） | 是非叶子但当前无子节点的"伪叶子"——`isLeaf=false` 但 `children=[]`；前端按非叶子渲染（无 application 列表 + 无展开按钮） | 显示 0/max 的一行 |

### 9.6 TypeScript 类型定义

新增 `src/api/types/score.ts`：

```typescript
export interface ScoreApplication {
  id: number                  // application.id
  name: string                // score_data.name 快照
  score: number
  created_at: string          // ISO datetime
}

export interface ScoreTreeNode {
  id: number
  name: string
  max: number
  score: number               // 封顶后
  raw: number                 // 封顶前
  depth: number               // preorder 累加，根 = 0
  isLeaf: boolean             // is_bind_template
  applications: ScoreApplication[]
  children: ScoreTreeNode[]
}

export interface ScoreTreeResponse {
  calculated_at: string
  total: number
  tree: ScoreTreeNode[]
}
```

### 9.7 边界情况

| 情况 | 处理 |
|---|---|
| 用户没有任何 PASSED application | `tree` 各节点 `score = 0`、`applications = []`，UI 展示全 0 行；总分为 0 |
| 用户有数据但 `template_category` 全停用 | `tree = []`，前端显示空状态 |
| 多根节点（"加分总计" + "扣分总计"） | 总分 `total` 是所有根 score 之和；前端渲染时各自独立展示，根节点上不显示 rootMax（最大为各根 max 之和，但 UI 不强制总和等于该值） |
| 分类被硬删除但学生历史 PASSED 申请还在 | score_data 行保留；但 recalculate 阶段该 category 不在树里，所以这条 application **不出现在任何叶子节点的 applications 列表中**——这条数据仅在 `GET /api/score/me` 失效；管理端列表视图仍可查 |
| 同叶子下有 100+ 条 PASSED 申请 | 不分页（recalculate 一次性拉出来）；如未来需要分页，把 `applications` 字段改为只返前 10 条 + count 字段，前端按需再发请求 |
| `raw > max` 同时该节点是叶子且 `applications` 为空 | 不可能（叶子 raw 只来自 score_data 求和，若 raw=0 但 max>0 才显示 0/max） |
| `recalculate` 进行中用户多次点击 | 前端 `recalculating` loading 锁按钮 + 后端 recalculate 自身幂等（多次写入同一 score_info） |
| 评分刷新过程中后台改了分类树 | recalculate 是"读时快照"——本次返回反映读时刻的树状态；下次再 recalculate 才反映新状态。可接受，不阻塞 |

### 9.8 性能与扩展

- **calculation 复杂度**：O(m + n)，m = 激活分类数（< 100），n = 该用户 score_data 行数（业务量级 < 200）。SQL 总数 5 条（含 application 列表）
- **多根 total**：当前为各根 `score` 之和。如果业务希望"扣分独立展示"则前端不要用 total，由卡片独立展示各根
- **历史成绩**：score_data 通过 `created_at` 日期范围查询历史 PASSED，不需 score_info 存历史（v4 设计）
- **MQ 异步扩展**：未来若希望 PASSED 后立即更新视图，将 recalculate 改为 MQ consumer 异步触发；前端 GET 接口检测到 `score_info` 过期则自动 recalculate 一次（即当前 get_summary 兜底逻辑）

### 9.9 相关文件清单（v1.1 新增）

```
src/
  services/
    score_data_service.py       # 升级：recalculate/get_summary 返回 tree
  app/routes/
    score.py                    # 接口返回值结构调整
idfrontend/src/
  api/types/
    score.ts                    # 新增：ScoreTreeNode / ScoreTreeResponse
  api/components/
    apiScore.ts                 # 新增/补全：getMyScore / recalculateScore
  views/profile/
    index.vue                   # 追加第三个 card「我的成绩」
```

### 9.10 实施顺序（v1.1）

1. **后端**：`score_data_service.py` 升级 `recalculate` / `get_summary` 返回结构（一次提交，包含 SQL 与组装逻辑）
2. **后端**：路由 `/api/score/me` 与 `/api/score/recalculate` 透传新结构
3. **前端**：新增 `score.ts` 类型
4. **前端**：`profile/index.vue` 加第三个 card + 完整渲染逻辑
5. **联调**：从空状态 → 提交一个 PASSED 申请 → 刷新 → 检查树形展开 + application 列表
6. **回归**：后台改 max_score → 学生刷新 → UI 比例变化

---

## 十、版本变更记录

| 版本 | 日期 | 改动 |
|---|---|---|
| v1.0 | 2026-07-08 | 初版：users 字段清理、/api/users/me、recalculate 算法 |
| v1.1 | 2026-07-08 | 新增第九章"我的成绩 - 学生前端展示"：recalculate 返回 tree 结构、profile 加第三个 card、扁平行渲染 + 嵌套 application card、停用分类过滤、政策变化适配矩阵 |

