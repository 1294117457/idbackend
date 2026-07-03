CREATE TABLE template_category (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    parent_id   INTEGER REFERENCES template_category(id),
    max_score   DECIMAL(5,2),
    sort_order  INTEGER DEFAULT 0,
    is_active   BOOLEAN DEFAULT TRUE,
    description VARCHAR(255),
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP
);

这里还有一个疑问，比如可能我会限制加分类型的最大值100分，学业加分等三个加分分别60，20，20，
这样还需要区分总申请最大值和单条最大值吗，后续申请是不是可以直接和叶子节点分类的最大值比较就好了
然后只要保证子分类的最大值和不超过父分类就没问题，
  同时后续学生计算分时从score_data更新到score_info时，增加分数的校验，
  这样在application层一层直接的申请的分数最大值校验，
  以及计算分数时校验子分类之和不超过父分类
这样是不是就没问题，然后每个分类就只需要一个最大值，