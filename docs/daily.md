
selectinload避免嵌套全量加载

继承ABC,协议Protocol，super

|super使用场景
|    中间件，继承一个框架中间件，
|        super调用父类的功能方法
|        另外加上自己的代码
|    异常
|        继承Exception，通过super调用基类的init方法报错

|python中的ABC,Protocol
|    python核心就是class Child(Parent)为基础实现继承
|    接口，抽象类也是在继承基础上实现
|    class A(ABC),定义抽象类，后续继承这个类必须实现所有方法
|    class B(Protocol)，定义接口，后续继承这个类，可以

|Storage实现
|    首先这里要有底层s3的适配器，然后有对应工厂比如StorageFactory,
|    然后depends从StorageFactory获取存储实例，
|    然后业务代码中（无论route或者service），直接通过depends注入这个实例就好了

|Depends作用
|    全局单例，测试时mock（暂时不了解），lifespan生命周期管理
|    全局单例，
|        代码中就是比如storage: BaseStorage = Depends(get_storage)这样获取全局单例

|lifesapn生命周期管理
|    redis,存储等实例，在应用启动时最好同步注册，在lifesapn中注册
|    llm等资源适合懒加载，在depends中基于lru_cache获取



minio资源获取问题

```
    富文本中存储图片url,
    如果用预签名会过期，直接获取minio文件会有安全问题
    1.nginx代理，minio单独一个rich-text目录公开可读，这里还是有暴露问题，
    2.BBF,backend for frontend,minio只对后端开放，后端拉去minio,redis缓存，返回给前端
```

```
1.前端部署是没有问题的
2.minio关闭公网访问，只基于docker network让后端服务访问
3.后端新增专门访问minio文件资源给前端的BFF端口
```

```
┌─────────────────────────────────────────────────────────────────────────┐
│  1. 编辑阶段（前端）                                                      │
│     用户粘贴/插入图片 → 上传到 /editor/upload → MinIO: editor/temp/{uuid}  │
│     → DOM 插入 <img src="editor://temp/{uuid}.{ext}">                    │
├─────────────────────────────────────────────────────────────────────────┤
│  2. 保存阶段（后端 sign_html）                                            │
│     接收 editor://temp/{uuid} → 移动到 editor/{entity}/{id}/{filename}   │
│     → 替换占位符为 editor://object/{entity}/{id}/{filename}              │
├─────────────────────────────────────────────────────────────────────────┤
│  3. 渲染阶段（后端 sign_html）                                            │
│     editor://object/template/123/uuid.png → 签名 URL                     │
├─────────────────────────────────────────────────────────────────────────┤
│  4. 删除阶段（后端 delete_by_entity）                                       │
│     删除 editor/template/{id}/*                                          │
└─────────────────────────────────────────────────────────────────────────┘
```







#### Embedding

```
src/
├── models/
│   └── embedding.py              # ✅ 已创建
├── repositories/
│   └── embedding_repo.py        # ✅ 已创建，向量 CRUD
├── services/
│   └── embedding_service.py     # ✅ 已创建，包含：
│       ├── parse_file()         # 解析文件 → txt
│       ├── chunk_text()         # 文本切块
│       ├── generate_embedding() # 调用 Qwen API
│       ├── upsert()            # 存向量
│       └── search()            # 向量检索
└── agent/
    └── graph/                  # Agent 直接调用 EmbeddingService
```

```
BM25（关键词搜索） 和向量搜索是两条并行的召回路径：

向量搜索：把 query 转成向量，用余弦相似度找语义相近的 chunk
BM25/关键词搜索：分析 query 和文档中关键词的词频统计关系（BM25 是一种更成熟的 TF-IDF 变体），找文字上直接匹配的 chunk
PostgreSQL 的全文检索靠 tsvector（文档）和 tsquery（查询词）匹配。plainto_tsquery('simple') 是把用户输入转成查询词的工具，但 'simple' 分词器只认空格和英文，会把中文逐字拆开。

举个例子，搜"推免工作"：

simple 分词器：拆成 '推' AND '免' AND '工' AND '作' 四个字，匹配任何含这四个单字的文档
zhparser（中文分词）：拆成 '推免' 和 '工作' 两个词，精确匹配
所以你的中文文档用 simple 分词几乎是无效的。zhparser 是专门为中文设计的分词器。
```

##### agent

```
Step A：ai_chat 基础（SSE + 会话）
src/
  app/routes/ai_chat.py      # POST /ai/chat/stream, POST /ai/chat/resume
  app/schemas/ai_chat.py     # ChatRequest, ResumeRequest, ChatMessageVO
  services/ai_chat_service.py # SSE 生成器，调用 agent.stream() / agent.resume()
  models/agent_session.py    # 会话表（已有 AgentSession，检查是否完整）
  models/agent_message.py    # 消息表（新建）
关键：先用 mock agent 跑通 SSE 流，先不写 LangGraph。等 SSE 跑通了再加 agent 逻辑。

Step B：src/agent（LangGraph 编排）
src/agent/
  state/__init__.py           # MainState, ConsultState, ApplyState
  nodes/
    classify_node.py          # LLM 意图分类
    consult/
      retrieve_node.py        # 调 embedding_service.rrf_search
      answer_node.py          # LLM 生成回答
    apply/
      gather_node.py
      fetch_templates_node.py
      ask_proof_node.py       # interrupt #1
      rag_match_node.py
      llm_rank_node.py
      select_template_node.py # interrupt #2
      redirect_node.py
  tools/__init__.py          # 工具函数
  graph/
    builder.py               # build_main_graph / consult_subgraph / apply_subgraph
    agent_service.py         # stream() / resume()
Step C：集成 + Human-in-the-Loop
把 Step A/B 连起来，补 interrupt 恢复逻辑。
```

##### 会话策略

| 策略     | 做法                    | 优点             | 缺点                     |
| :------- | :---------------------- | :--------------- | :----------------------- |
| 全量存储 | 每条消息都存原始内容    | 完整、可回放     | 数据量随对话线性增长     |
| 分级存储 | 热/温/冷分层（按时间）  | 可平衡成本和性能 | 实现复杂，需要定期迁移   |
| 摘要压缩 | 每 M 条生成摘要，删原始 | 大幅减少 token   | 摘要质量不稳定，丢细节   |
| 向量存储 | 转成向量存向量库        | 语义检索         | 丢失顺序，精确内容不可控 |
| 混合存储 | 原始+摘要+向量组合      | 灵活             | 最复杂                   |

## 读取策略

| 策略          | 做法                          | 适合场景         |
| :------------ | :---------------------------- | :--------------- |
| 滑动窗口      | 只取最近 N 条                 | 大多数对话       |
| 全量读取      | 一次取完                      | 短对话（<20 轮） |
| 分页加载      | 前端滚动，API 分页            | 前端展示历史     |
| 摘要+细节     | 旧消息用摘要，需要时展开      | 超长对话         |
| 语义检索      | 问"上次我说过xxx"，向量库检索 | 定位历史内容     |
| 关键节点+窗口 | 标记重要节点 + 最近消息       | 需要保留决策点   |

```
┌─────────────────────────────────────────────┐
│            users（用户表）                   │
│  id, name, email, ...                       │
└─────────────────┬───────────────────────────┘
                  │ 1 : N
                  ↓
┌─────────────────────────────────────────────┐
│            sessions（会话容器）              │  ← 你缺的这一层！
│  id, user_id, title, created_at, ...        │
└─────────────────┬───────────────────────────┘
                  │ 1 : N
                  ↓
┌─────────────────────────────────────────────┐
│     messages（消息全量存储）                 │
│  id, session_id, role, content, created_at  │
└────────┬─────────────────────┬──────────────┘
         │ 1:1                 │ 1:1
         ↓                     ↓
┌─────────────────┐   ┌──────────────────────┐
│ message_        │   │ session_snapshots    │
│ embeddings      │   │ （会话元数据快照）    │
│ （消息向量）     │   │ total_msg_count,     │
└─────────────────┘   │ last_preview, ...    │
                      └──────────┬───────────┘
                                 │ 1 : N（一个会话可以有多个摘要）
                                 ↓
                      ┌──────────────────────┐
                      │ session_summaries    │
                      │ （阶段性摘要）        │
                      │ summary_text,        │
                      │ msg_start_id,        │
                      │ msg_end_id           │
                      └──────────────────────┘
```

```
我想的是message存储、session_summary压缩等都是必须的，但是不必要每次都调用，类似tool一样暴露给agetn
agent要有一个classifynode,先用于判断用户意图，再选择下一步怎么做，如果每次对话都携带summary、rag等，会不会内容过于多反而有噪音呢？

比如用户可能输入一个日常对话聊天，和业务无关就进入普通聊天node？用户输入的意图是咨询政策，就进入政策咨询节点，结合用户输入查询rag返回给用户，
比如用户的意图是让agent帮忙找到需要的template,就进入applyNode,基于用户输入结合rag中有的template和rag的政策文件，给用户找到需要的template返回？

不过这里classifynode实际之根据用户输入来判断确实可能缺少上下文语义

所以就是每次对话，先进入claasifynode,此时携带用户输入，session_summary和最近对话，在classifynode判断用户意图，然后进入后续的node对吗
这样就是要在基础业务层就做好对话压缩，上下文，用户输入的组合对吗
```

```
好的，那就暂定这个方法，
	一个classifynode,
	加上chat_node,consult_node,apply_node,

用户每次输入都到classifyNode,然后判断下一步去哪个node进行后续业务逻辑，你觉得怎么样
	以及可能consult_node也可以中途识别到对应template
	,中途调用apply_node获取template_id返回给用户让其选择对不对


```

## 总结

| 组件                     | 放在业务层 | 放在 LangGraph |
| :----------------------- | :--------: | :------------: |
| 会话元信息（用户、时间） |     ✅      |                |
| 原始消息存储             |     ✅      |                |
| 会话摘要                 |     ✅      |                |
| 图节点状态传递           |            |       ✅        |
| RAG 结果                 |            |       ✅        |
| 工具调用中间结果         |            |       ✅        |
| 断点恢复                 |            |       ✅        |