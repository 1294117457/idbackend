##### 

## 当前 score_data 能否支撑算法

完全够用，来对应一下：

| 算法需要                 | score_data 提供                             |
| :----------------------- | :------------------------------------------ |
| 按用户 + 学年 + 分类分组 | `user_id` + `academic_year` + `category_id` |
| 求该叶子分类的原始总分   | `SUM(score)`                                |
| 追溯这条分数来自哪个申请 | `application_id`                            |
| 显示用                   | `name`（模板名快照）                        |

#### 分数算法

```
SELECT category_id, SUM(score) AS raw_sum
FROM score_data
WHERE user_id = :user_id AND is_active = TRUE
GROUP BY category_id算法只需一条聚合 SQL：

SELECT category_id, SUM(score) as raw_sum

FROM score_data

WHERE user_id = ? AND academic_year = ?

GROUP BY category_id
```

```
all_categories = SELECT * FROM template_category WHERE is_active = TRUE
# 按 parent_id 组装成树，O(n) 一次遍历
node_map = {c.id: c for c in all_categories}
for c in all_categories:
    c.children = []
for c in all_categories:
    if c.parent_id:
        node_map[c.parent_id].children.append(c)
roots = [c for c in all_categories if not c.parent_id]
```

```
def calc(node, leaf_scores) -> float:
    if not node.children:
        raw = leaf_scores.get(node.id, 0.0)
        return min(raw, node.max_score) if node.max_score else raw
    
    children_sum = sum(calc(child, leaf_scores) for child in node.children)
    return min(children_sum, node.max_score) if node.max_score else children_sum
```

```
result = {}

def collect(node, leaf_scores):
    score = calc(node, leaf_scores)
    result[str(node.id)] = {
        "name": node.name,
        "score": score,
        "max": float(node.max_score) if node.max_score else None
    }
    for child in node.children:
        collect(child, leaf_scores)

for root in roots:
    collect(root, leaf_scores)

UPDATE users SET score_info = result WHERE id = user_id
```

##### 3设计字段

```
CREATE TABLE score_data (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id),
    application_id INTEGER NOT NULL REFERENCES score_applications(id),
    category_id    INTEGER NOT NULL REFERENCES template_category(id),
    name           VARCHAR(100),
    score          DECIMAL(5,2) NOT NULL,
    is_active      BOOLEAN DEFAULT TRUE,
    created_at     TIMESTAMP DEFAULT NOW()
);
```

