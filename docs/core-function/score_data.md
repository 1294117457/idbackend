# score_data 实施指南（v4.2）

> **配套文档**：[四层职责设计 § 4 ScoreData（流水记录）](./四层职责设计.md#4-scoreData流水记录)
>
> 本指南给出 score_data 的**实施层面**细节：表结构、聚合算法、recalculate 触发的 service 接口与路由。

---

## 一、schema（最终版）

```sql
CREATE TABLE score_data (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id),
    application_id INTEGER NOT NULL REFERENCES applications(id),
    category_id    INTEGER NOT NULL REFERENCES template_category(id),  -- 叶子节点
    name           VARCHAR(100),                  -- 模板名快照，展示用
    score          DECIMAL(5,2) NOT NULL,         -- application.apply_score 快照（不是 gain_score）
    is_active      BOOLEAN DEFAULT TRUE,          -- FALSE = 该申请被外部标记为失效，recalculate 时排除
    created_at     TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_score_data_user_active ON score_data(user_id, is_active);
CREATE INDEX idx_score_data_user_category ON score_data(user_id, category_id);
CREATE INDEX idx_score_data_application ON score_data(application_id);
```

**v4.2 vs v4.1 的差异：**

- v4.1 中 `score = application.gain_score` 快照——v4.2 改为 `score = application.apply_score` 快照（同一数值，但语义更直观：写入的就是申请快照，避免与 gain_score 字段双倍维护）
- 不需要 `academic_year` 字段（本期不区分学年，历史查询靠 `created_at` 过滤）

**v4.2 与 application 的协作：**

`score_data` 的写入时机**仅在 application.status → PASSED 时触发**：

- `review_count = 1`：单个审核员投 PASS → PASSED → 同事务写 score_data
- `review_count ≥ 2`：第 N 个审核员投 PASS 触发 PASSED → 同事务写 score_data

无论哪种 review_count，score_data 都只在"application 整体通过"那一刻写入——**proof 状态变化不影响 score_data**（proof 是辅助表）。如果审核员在 APPLYING 阶段反复修改 proof.status（veto 视角下覆盖前审核员的决定），score_data 不会被多次写入，因为 application.status 不会因此变化。

---

## 二、ScoreDataService 接口

### 2.1 `record()` —— application 通过时调用

```python
async def record(db, user_id: int, application_id: int,
                 category_id: int, name: str, score: Decimal):
    """
    写入一条流水，由 ApplicationService.pass_application() 在同一事务内调用。
    
    输入:
      - user_id: 学生 id
      - application_id: 已 PASSED 的 application
      - category_id: application.category_id（叶子分类）
      - name: application.template_name（快照展示用）
      - score: application.apply_score（已通过审核的最终分数）
    
    行为:
      - INSERT INTO score_data (..., is_active=TRUE)
      - **不触发** recalculate（v4.2 决策——解耦到独立接口）
    
    事务: 与 pass_application 同事务（atomic）
    """
```

**调用方**：`ApplicationService.pass_application()` 的第 c 步（同事务）。

### 2.2 `recalculate()` —— 学生端 / 管理端按需触发

```python
async def recalculate(db, user_id: int) -> dict:
    """
    全量聚合 + 覆盖写 user.score_info，幂等可反复触发。
    
    算法（4 步）:
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
    
    性能: 2 次 SELECT + 1 次 UPDATE，全过程内存递归，无 N+1
    
    返回:
      - user.score_info 字典：{
          "calculated_at": ISO datetime,
          "categories": {"<category_id>": {"name", "score", "max"}, ...},
          "total": float
        }
    
    触发方（三种入口）：
      1. 学生端"刷新成绩"按钮 → POST /api/score/recalculate
      2. 管理端"批量重算" → POST /api/score/recalculate-all
      3. 管理端"单用户重算" → POST /api/score/recalculate-by-admin?user_id=?
    """
```

### 2.3 `get_summary()` —— 学生端只读展示

```python
async def get_summary(db, user_id: int) -> dict:
    """
    读取 user.score_info 快照，不重算。
    返回:
      - 命中: {"hit": True, "score_info": {...}}
      - 未命中: 触发一次 recalculate（兜底），返回计算后的 score_info
    """
```

**为什么兜底触发 recalculate**：学生拉"我的成绩"时，user.score_info 可能因为各种延迟还未更新（recalculate 是解耦触发的）。兜底一次同步重算保证前端能拿到数据；性能上 recalculate 是 O(1) SQL × 3，可接受。

---

## 三、recalculate 触发架构（v4.2 决策）

### 3.1 时序图

```
[application.pass_application]
        │
        ├─ 写 score_data 行（同一事务）
        └─ application.status → PASSED（同一事务）
                  ↓
[recalculate]** 不再被自动调用 **
                  ↓
[独立的 recalculate 入口]
        │
        ├─ 学生端"刷新成绩"按钮
        │     └─ POST /api/score/recalculate
        │           └─ ScoreDataService.recalculate(student.user_id)
        │
        ├─ 管理端"批量重算"
        │     └─ POST /api/score/recalculate-all
        │           └─ 遍历 students + 多线程调 recalculate
        │
        └─ 管理端"单用户重算"
              └─ POST /api/score/recalculate-by-admin?user_id=?
                    └─ ScoreDataService.recalculate(target.user_id)
```

### 3.2 v4.1 → v4.2 触发策略对比

| 维度 | v4.1（同步触发） | v4.2（解耦触发） |
|---|---|---|
| 触发时机 | `application.pass_application` 同事务 | 学生 / 管理员手动触发 |
| user.score_info 更新延迟 | 0（强一致） | 用户调 recalculate 后才有 |
| application 事务失败风险 | 受 score_data / score_info 写入影响 | 只受 score_data 影响 |
| MQ 接入工作量 | 需要重构（recalculate 拆出） | 接口形态直接对接 MQ consumer |
| 性能 | 单 application 耗时 +1 次 recalculate | recalculate 按需执行，可分散 |

### 3.3 v4.2 触发的妥协

学生 PASSED 后**立即**看不到总分，必须点"刷新成绩"按钮。这是 v4.2 的权衡点：

- **接受场景**：学生量级 ≤ 10k，recalculate 3 条 SQL，同步调用响应快
- **不接受场景**：高频 PASSED 后立即展示 → 改用 v4.1 方案 / MQ

如未来需要立即展示，改用 MQ 异步方案：
- `pass_application` 发 MQ 消息 `(user_id, application_id)`
- consumer 收到后调 `recalculate(user_id)`
- 前端轮询 `get_summary` 检测 `score_info.calculated_at` 变化

---

## 四、聚合算法详解

### 4.1 为什么 score_data 表要按 category_id GROUP BY？

`score_data` 存的是"每个 PASSED 的 application 贡献到哪个叶子分类多少分"——**叶子分类**粒度。recalculate 用 `category_id GROUP BY` 一条 SQL 拿到该学生所有叶子分类的原始总分。

### 4.2 内存封顶树遍历

```python
def collect(node, leaf_scores):
    score = calc(node, leaf_scores)
    result[str(node.id)] = {
        "name": node.name,
        "score": score,
        "max": float(node.max_score) if node.max_score else None
    }
    for child in node.children:
        collect(child, leaf_scores)

def calc(node, leaf_scores):
    if not node.children:
        raw = leaf_scores.get(node.id, 0.0)
        return min(raw, node.max_score) if node.max_score else raw
    children_sum = sum(calc(child, leaf_scores) for child in node.children)
    return min(children_sum, node.max_score) if node.max_score else children_sum

# 入口
all_categories = SELECT * FROM template_category WHERE is_active = TRUE
node_map = {c.id: c for c in all_categories}
for c in all_categories:
    c.children = []
for c in all_categories:
    if c.parent_id:
        node_map[c.parent_id].children.append(c)
roots = [c for c in all_categories if not c.parent_id]

leaf_scores = SELECT category_id, SUM(score) AS raw_sum
              FROM score_data
              WHERE user_id = ? AND is_active = TRUE
              GROUP BY category_id

result = {}
for root in roots:
    collect(root, leaf_scores)

UPDATE users SET score_info = result WHERE id = user_id
```

### 4.3 后序遍历示例（4 层树）

```
加分总计(max=100)
  └── 加分(max=80)
        ├── 学业(max=60)
        │     ├── 竞赛(raw=25, max=20)
        │     └── 论文(raw=15, max=10)
        └── 专长(max=30)
              └── 体育(raw=35, max=30)

执行顺序（后序）:
  1. 竞赛 capped = min(25, 20) = 20
  2. 论文 capped = min(15, 10) = 10
  3. 学业 capped = min(20 + 10, 60) = 30
  4. 体育 capped = min(35, 30) = 30
  5. 专长 capped = min(30, 30) = 30  (只有体育一个叶子，sum=30)
  6. 加分 capped = min(30 + 30, 80) = 60
  7. 总计 capped = min(60, 100) = 60

最终 user.score_info:
{
  "calculated_at": "2026-07-06T...",
  "categories": {
    "1": { "name": "加分总计",  "score": 60.0, "max": 100.0 },
    "2": { "name": "加分",      "score": 60.0, "max": 80.0  },
    "3": { "name": "学业加分",  "score": 30.0, "max": 60.0  },
    "4": { "name": "竞赛奖项",  "score": 20.0, "max": 20.0  },
    "5": { "name": "学术论文",  "score": 10.0, "max": 10.0  },
    "6": { "name": "专长加分",  "score": 30.0, "max": 30.0  },
    "7": { "name": "体育",      "score": 30.0, "max": 30.0  }
  },
  "total": 60.0
}
```

---

## 五、`user.score_info` 字段定义

```sql
-- users 表新增（与四层职责设计 § 5 一致）
ALTER TABLE users ADD COLUMN score_info JSONB DEFAULT '{}';
ALTER TABLE users ADD COLUMN extra_info JSONB DEFAULT '{}';
```

**`score_info` JSON 结构**：

```jsonc
{
  "calculated_at": "2026-07-06T10:00:00+08:00",  // 上次 recalculate 时间（用于前端判断是否有新数据）
  "categories": {
    "1": { "name": "加分总计",  "score": 60.0, "max": 100.0 },
    "2": { "name": "加分",      "score": 60.0, "max": 80.0  },
    // ... 包含所有层级的分类（含非叶节点），key 是 category_id 字符串
  },
  "total": 60.0  // 根节点 score
}
```

**前端约定**：

- 读 `score_info.categories["<category_id>"]` 展示
- 历史分数查询直接查 `score_data` 表按 `created_at` 过滤，不靠 score_info 存历史

---

## 六、MQ 扩展点（v4.2 不实现，前向兼容）

未来如果改成"pass_application 发 MQ，consumer 异步重算"，MQ 消息格式预定义：

```jsonc
{
  "event": "application.passed",
  "user_id": 123,
  "application_id": 456,
  "score": 8.0,
  "category_id": 3,
  "passed_at": "2026-07-06T..."
}
```

**consumer**：

```python
async def on_application_passed(msg):
    user_id = msg["user_id"]
    await ScoreDataService.recalculate(db, user_id)
```

这一改造把 recalculate 触发与 application 业务彻底解耦，v4.2 只用"学生手动 / 管理员手动"两种入口即可——MQ 是迁移路径上的下一步。

---

## 七、未决项与已知妥协

| 项 | 当前决策 | 替代方案 |
|---|---|---|
| recalculate 触发时机 | 学生 / 管理员手动 | MQ 异步 / 同事务同步 |
| score 是否包含历史未启用分类 | 否（`is_active=TRUE` 过滤） | 保留时按 `category.is_active` 重新计算 |
| 多用户批量 recalculate | 顺序遍历 | 并行（注意 score_data 行锁） |
| score_info 空对象兜底 | `get_summary` 检测空则 recalculate 一次 | 由前端判断后强制刷新 |
| 历史归档 | 不实现 | 定期把 `is_active=FALSE` 的 score_data 移到归档表 |

---

## 八、相关文件清单

```
src/
  models/
    score_data.py              # ScoreData model
    user.py                    # User + score_info / extra_info JSONB
  services/
    score_data_service.py      # record / recalculate / get_summary
  app/routes/
    score.py                   # recalculate / get_summary / recalculate-all
```

实施时**严格按本指南落地**；如有新需求先回本指南增改章节再写代码。
