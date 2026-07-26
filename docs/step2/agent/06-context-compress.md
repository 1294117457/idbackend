# AI Agent · Step 3 · 会话上下文压缩与摘要合并

> 本文档是 Step 3 的延伸专题：设计 `agent_session_snapshots` 和 `agent_session_summaries` 两张表的"压缩状态机"模型，实现"每 20 条消息触发一次摘要 + 3 个近期摘要滚动归档"的方案。

---

## 1. 背景与目标

### 1.1 现状问题

当前 `agent_session_snapshots` 模型字段：

| 字段 | 类型 | 用途 | 问题 |
|------|------|------|------|
| `message_count` | Integer | 消息总数 | 每次写消息都要 +1，高并发写竞争 |
| `last_message_at` | DateTime | 最后消息时间 | 无法精确判断触发时机 |
| `needs_compress` | Boolean | 是否需要压缩 | 写入逻辑分散在多处 |

`summaries` 表无 `is_archived` 字段，无法区分"近期摘要"和"历史摘要"。

### 1.2 设计目标

1. **降低 DB 写入频率**：不再每次写消息都更新 snapshot
2. **精确触发判断**：用 seq 差值而非计数器
3. **容量可控**：近期摘要固定 3 个，多了就合并到历史摘要
4. **职责单一**：snapshot 只在压缩时变化，summary 通过 `is_archived` 区分两类

### 1.3 关键策略（与 daily.md 对齐）

```
触发: 累计 20 条新消息 → 压缩一次
窗口: 最近 20 条消息 + 3 个近期摘要 + 1 个历史摘要
合并: 近期摘要满 3 个 → 最旧的合并到历史摘要
```

---

## 2. 数据模型变更

### 2.1 `AgentSessionSnapshot` 表

#### 2.1.1 字段变更

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `id` | Integer | ✅ | auto | 主键 |
| `session_id` | Integer | ✅ | - | 会话ID，Unique 索引 |
| `last_summary_end_seq` | **Integer** | ✅ | 0 | **新增**：上次摘要覆盖的最后一条消息 seq |
| `recent_summary_count` | **Integer** | ✅ | 0 | **新增**：当前"近期摘要"数量 |
| `last_summary_at` | DateTime | ❌ | NULL | **新增**：上次压缩时间 |
| `total_summary_count` | **Integer** | ✅ | 0 | **新增**：总摘要数（含历史） |
| `created_at` | DateTime | ✅ | now() | 创建时间 |
| `updated_at` | DateTime | ✅ | now() | 更新时间 |

#### 2.1.2 字段说明

- **`last_summary_end_seq`**：判断压缩触发的核心字段
  - 不存在 snapshot 时：累计到 seq=20 才触发
  - 存在 snapshot 时：`latest_seq - last_summary_end_seq >= 20` 触发

- **`recent_summary_count`**：冗余字段，避免每次查询都 `COUNT(*)`
  - 压缩时更新
  - 仅用于快速判断"近期摘要是否要合并"

- **`total_summary_count`**：用于前端展示"本会话累计压缩 N 次"

- **去掉 `total_message_count`**：避免每次写消息都更新 snapshot
  - 最新 seq 通过 `SELECT MAX(seq) FROM agent_messages WHERE session_id = ?` 查询
  - seq 上有索引，查询成本可忽略

- **删除字段**：`message_count` / `last_message_at` / `needs_compress` / `total_message_count`（旧设计 + 新设计都不要）

### 2.2 `AgentSessionSummary` 表

#### 2.2.1 字段变更

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `id` | Integer | ✅ | auto | 主键 |
| `session_id` | Integer | ✅ | - | 会话ID，索引 |
| `summary` | Text | ✅ | - | 摘要内容 |
| `start_seq` | Integer | ✅ | 0 | 覆盖起始 seq |
| `end_seq` | Integer | ✅ | 0 | 覆盖结束 seq |
| `is_archived` | **Boolean** | ✅ | **false** | **新增**：false=近期，true=历史 |
| `created_at` | DateTime | ✅ | now() | 创建时间 |
| `updated_at` | DateTime | ✅ | now() | 更新时间 |

#### 2.2.2 字段说明

- **`is_archived`**：分类核心字段
  - `false`：近期摘要，最多保留 3 个
  - `true`：历史摘要，1 个会话最多保留 1 个

### 2.3 ORM 模型代码

```python
# src/models/ai_chat.py （改造）

class AgentSessionSnapshot(Base, TimestampMixin):
    """AI 会话快照（记录压缩状态）"""
    __tablename__ = "agent_session_snapshots"

    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    # 上次摘要覆盖的最后 seq（核心字段）
    last_summary_end_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 当前近期摘要数量
    recent_summary_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 上次压缩时间
    last_summary_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 总摘要数（含历史）
    total_summary_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AgentSessionSummary(Base, TimestampMixin):
    """AI 会话摘要"""
    __tablename__ = "agent_session_summaries"

    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    start_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 区分近期/历史
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

---

## 3. 压缩触发逻辑

### 3.1 触发判断（不写计数器）

```python
# src/services/compress_service.py
async def should_compress(db: AsyncSession, session_id: int) -> bool:
    """判断是否需要触发压缩
    
    核心: 用 seq 差值，不用每次消息都更新计数器
    """
    snapshot = await AIChatRepository.get_snapshot(db, session_id)
    latest_seq = await AIChatRepository.get_latest_seq(db, session_id)
    
    if latest_seq is None:
        return False
    
    if snapshot is None:
        # 首次: 总消息数 >= 20 才触发
        return latest_seq >= 20
    
    # 非首次: 距离上次摘要的 seq 差值 >= 20
    diff = latest_seq - snapshot.last_summary_end_seq
    return diff >= 20
```

### 3.2 为什么用 seq 差值

| 方案 | 写消息时操作 | 读 snapshot 频率 | 一致性 |
|------|------------|-----------------|--------|
| 旧：每次 +1 counter | 1 次写 snapshot | 低 | 有竞态（需锁） |
| **新：seq 差值** | **0 次写 snapshot** | **每次判断都查** | **天然一致** |

`seq` 是消息表的自增字段，已经是权威来源。snapshot 只在压缩时更新，避免竞争。

---

## 4. 压缩执行流程

### 4.1 主流程

```python
# src/services/compress_service.py
async def do_compress(db: AsyncSession, session_id: int) -> Optional[int]:
    """执行压缩
    
    Returns: 新摘要 ID（如有）
    """
    snapshot = await AIChatRepository.get_snapshot(db, session_id)
    latest_seq = await AIChatRepository.get_latest_seq(db, session_id)
    
    # 1. 计算压缩范围
    if snapshot:
        start_seq = snapshot.last_summary_end_seq + 1
    else:
        start_seq = 1
    end_seq = latest_seq
    
    if end_seq - start_seq + 1 < 20:
        return None  # 不够压缩
    
    # 2. 取出待压缩消息
    messages = await AIChatRepository.get_messages_range(
        db, session_id, start_seq, end_seq
    )
    
    # 3. 调用 LLM 生成摘要
    summary_text = await _generate_summary(messages)
    
    # 4. 保存新摘要（近期）
    new_summary = await AIChatRepository.create_summary(
        db,
        session_id=session_id,
        summary=summary_text,
        start_seq=start_seq,
        end_seq=end_seq,
        is_archived=False,
    )
    await db.flush()
    
    # 5. 检查近期摘要数量, 超出则合并
    recent_summaries = await AIChatRepository.list_summaries(
        db, session_id, is_archived=False, order_by='end_seq ASC'
    )
    if len(recent_summaries) > settings.summary_recent_max_count:
        await _merge_oldest_to_archive(db, session_id)
        recent_summaries = recent_summaries[1:]  # 移除最旧的
    
    # 6. 更新 snapshot（不存 total_message_count）
    await AIChatRepository.upsert_snapshot(
        db,
        session_id=session_id,
        last_summary_end_seq=end_seq,
        recent_summary_count=len(recent_summaries),
        last_summary_at=datetime.now(timezone.utc),
        total_summary_count=len(recent_summaries) + 1,  # +1 是历史摘要
    )
    
    await db.commit()
    return new_summary.id
```

### 4.2 LLM 摘要生成

```python
async def _generate_summary(messages: List[AgentMessage]) -> str:
    """调用 LLM 生成摘要"""
    from src.infra.ai.model import get_chat_model
    
    text = "\n".join([
        f"[{m.role.value}] {m.content}"
        for m in messages
    ])
    
    prompt = f"""请将以下对话历史压缩为简洁摘要（200字以内），
保留关键信息：用户意图、已获取的事实、已做出的决定、待办事项。

对话历史:
{text}

摘要:"""
    
    llm = get_chat_model()
    response = await llm.ainvoke(prompt)
    return response.content
```

---

## 5. 摘要合并逻辑

### 5.0 整体结构与约束

一个 session 最多同时拥有：
- **历史摘要** 1 条（is_archived=true，合并态，≤ ARCHIVED_MAX_CHARS 字）
- **近期摘要** 最多 RECENT_MAX_COUNT 条（is_archived=false，独立，每条 ≤ RECENT_MAX_CHARS 字）

```
┌─────────────────────────────────────────────────────────────────┐
│  整体大小恒定:                                                   │
│  - 历史摘要: ARCHIVED_MAX_CHARS 字                              │
│  - 近期摘要: RECENT_MAX_COUNT × RECENT_MAX_CHARS 字             │
│  - 总摘要 token = 历史 + 近期, 不会膨胀                          │
│                                                                 │
│  新摘要生成时:                                                   │
│  - 新摘要进入近期                                                │
│  - 若近期超过 RECENT_MAX_COUNT                                   │
│    → 把最早的近期摘要合并到历史                                  │
│  - 整体大小恢复平衡                                              │
└─────────────────────────────────────────────────────────────────┘
```

### 5.1 合并最旧近期摘要到历史

```python
async def _merge_oldest_to_archive(db: AsyncSession, session_id: int) -> None:
    """合并最旧的近期摘要到历史摘要
    
    流程:
    1. 取最旧的近期摘要
    2. 查找现有历史摘要
       - 有: LLM 合并两条, 扩展 seq 范围, 删除被合并的近期摘要
       - 无: 把最旧的近期摘要升级为历史摘要
    3. 防御性: 检查历史摘要字数, 超 ARCHIVED_MAX_CHARS 触发再压缩
    """
    # 1. 取最旧的近期摘要
    recent = await AIChatRepository.list_summaries(
        db, session_id, is_archived=False, order_by='end_seq ASC', limit=1
    )
    if not recent:
        return
    oldest = recent[0]
    
    # 2. 查找历史摘要
    archived = await AIChatRepository.list_summaries(
        db, session_id, is_archived=True, limit=1
    )
    
    if archived:
        # 2a. 已有历史摘要, LLM 合并
        archive = archived[0]
        merged_text = await _merge_summary_texts(
            old_text=archive.summary,
            new_text=oldest.summary,
            target_chars=settings.summary_merge_target_chars,
        )
        archive.summary = merged_text
        archive.start_seq = min(archive.start_seq, oldest.start_seq)
        archive.end_seq = oldest.end_seq
        await db.flush()
        # 删除被合并的近期摘要
        await AIChatRepository.delete_summary(db, oldest.id)
    else:
        # 2b. 没有历史摘要, 直接把最旧的近期升级为历史
        oldest.is_archived = True
        await db.flush()
    
    # 3. 防御性: 历史摘要超阈值时再压缩
    final_archived = await AIChatRepository.list_summaries(
        db, session_id, is_archived=True, limit=1
    )
    if final_archived and len(final_archived[0].summary) > settings.summary_archived_max_chars:
        final_archived[0].summary = await _resummarize_text(
            text=final_archived[0].summary,
            target_chars=settings.summary_archived_max_chars,
        )
        await db.flush()
```

### 5.2 文本合并 (LLM)

```python
async def _merge_summary_texts(
    old_text: str,
    new_text: str,
    target_chars: int,
) -> str:
    """合并两段摘要文本, 用 LLM 重新生成一段更精炼的合并摘要"""
    from src.infra.ai.model import get_chat_model
    
    prompt = f"""将以下两段历史摘要合并为一段（{target_chars} 字以内），
保留所有关键信息:
- 用户意图、事实、决定、待办
- 去除重复描述、舍弃次要细节

摘要A (较早):
{old_text}

摘要B (较新):
{new_text}

合并后的摘要:"""
    
    llm = get_chat_model()
    response = await llm.ainvoke(prompt)
    return response.content
```

### 5.3 文本再压缩 (LLM)

```python
async def _resummarize_text(text: str, target_chars: int) -> str:
    """当历史摘要超过阈值时, 用 LLM 重新压缩"""
    from src.infra.ai.model import get_chat_model
    
    prompt = f"""以下历史摘要过长，请重新压缩到 {target_chars} 字以内。
保留所有关键信息，舍弃次要细节。

当前摘要:
{text}

压缩后的摘要:"""
    
    llm = get_chat_model()
    response = await llm.ainvoke(prompt)
    return response.content
```

### 5.4 触发流程图

```
压缩触发时 (每 SUMMARY_COMPRESS_INTERVAL 条消息):
  ↓
1. 生成新摘要 (调用 LLM, ≤ RECENT_MAX_CHARS 字)
  ↓
2. 写入 agent_session_summaries (is_archived=false)
  ↓
3. 检查当前近期摘要数量
   ├─ 数量 ≤ RECENT_MAX_COUNT: 结束
   └─ 数量 > RECENT_MAX_COUNT: 调用 _merge_oldest_to_archive
                                    ↓
                                  a. 取最旧近期
                                  b. 合并/升级历史
                                  c. 删除被合并的近期
                                  d. 检查历史大小, 超阈值再压缩
```

### 5.5 数据演化示例

```
假设: SUMMARY_COMPRESS_INTERVAL=20, RECENT_MAX_COUNT=3

seq 1-20   → 摘要A (recent, end_seq=20)
seq 21-40  → 摘要B (recent, end_seq=40)
seq 41-60  → 摘要C (recent, end_seq=60)
            DB: recent=[A,B,C], archived=[]

seq 61-80  → 摘要D (recent, end_seq=80)  ← 第 4 个, 触发合并
            合并逻辑:
              - 最旧近期=A, 现有历史=空
              - A 直接升级为历史
            DB: recent=[B,C,D], archived=[A(1-20)]

seq 81-100 → 摘要E (recent, end_seq=100)  ← 第 4 个, 触发合并
            合并逻辑:
              - 最旧近期=B, 现有历史=A
              - LLM 合并 A+B → 新历史(1-40)
              - 删除 B
            DB: recent=[C,D,E], archived=[AB(1-40)]
```

---

## 6. Repository 层设计

### 6.1 需要新增的查询

```python
# src/repositories/ai_chat_repo.py （改造）

class AIChatRepository:
    # ─── Snapshot 操作 ───
    
    @staticmethod
    async def get_snapshot(db: AsyncSession, session_id: int) -> Optional[AgentSessionSnapshot]:
        """获取 session 的 snapshot"""
        stmt = select(AgentSessionSnapshot).where(
            AgentSessionSnapshot.session_id == session_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    @staticmethod
    async def upsert_snapshot(
        db: AsyncSession,
        session_id: int,
        last_summary_end_seq: int,
        recent_summary_count: int,
        last_summary_at: datetime,
        total_summary_count: int,
    ) -> AgentSessionSnapshot:
        """插入或更新 snapshot

        注意: 不存 total_message_count, 用 MAX(seq) 查询
        """
        snapshot = await AIChatRepository.get_snapshot(db, session_id)
        if snapshot:
            snapshot.last_summary_end_seq = last_summary_end_seq
            snapshot.recent_summary_count = recent_summary_count
            snapshot.last_summary_at = last_summary_at
            snapshot.total_summary_count = total_summary_count
        else:
            snapshot = AgentSessionSnapshot(
                session_id=session_id,
                last_summary_end_seq=last_summary_end_seq,
                recent_summary_count=recent_summary_count,
                last_summary_at=last_summary_at,
                total_summary_count=total_summary_count,
            )
            db.add(snapshot)
        await db.flush()
        return snapshot
    
    # ─── Summary 操作 ───
    
    @staticmethod
    async def list_summaries(
        db: AsyncSession,
        session_id: int,
        is_archived: bool = False,
        order_by: str = 'created_at ASC',
        limit: Optional[int] = None,
    ) -> List[AgentSessionSummary]:
        """查询摘要列表"""
        stmt = select(AgentSessionSummary).where(
            AgentSessionSummary.session_id == session_id,
            AgentSessionSummary.is_archived == is_archived,
        )
        # order_by 处理
        if order_by == 'end_seq ASC':
            stmt = stmt.order_by(AgentSessionSummary.end_seq.asc())
        elif order_by == 'created_at ASC':
            stmt = stmt.order_by(AgentSessionSummary.created_at.asc())
        if limit:
            stmt = stmt.limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())
    
    @staticmethod
    async def delete_summary(db: AsyncSession, summary_id: int) -> None:
        """删除单条摘要"""
        summary = await db.get(AgentSessionSummary, summary_id)
        if summary:
            await db.delete(summary)
            await db.flush()
    
    # ─── Message 查询 ───
    
    @staticmethod
    async def get_latest_seq(db: AsyncSession, session_id: int) -> Optional[int]:
        """获取最新消息 seq"""
        stmt = select(func.max(AgentMessage.seq)).where(
            AgentMessage.session_id == session_id
        )
        result = await db.execute(stmt)
        return result.scalar()
    
    @staticmethod
    async def get_messages_range(
        db: AsyncSession,
        session_id: int,
        start_seq: int,
        end_seq: int,
    ) -> List[AgentMessage]:
        """按 seq 范围取消息"""
        stmt = select(AgentMessage).where(
            AgentMessage.session_id == session_id,
            AgentMessage.seq >= start_seq,
            AgentMessage.seq <= end_seq,
        ).order_by(AgentMessage.seq.asc())
        result = await db.execute(stmt)
        return list(result.scalars().all())
    
    @staticmethod
    async def list_recent_messages(
        db: AsyncSession,
        session_id: int,
        limit: int = 20,
    ) -> List[AgentMessage]:
        """取最近 N 条消息（按 seq 倒序）"""
        stmt = select(AgentMessage).where(
            AgentMessage.session_id == session_id,
        ).order_by(AgentMessage.seq.desc()).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())
```

---

## 7. 上下文组装

### 7.1 `build_context` 设计

```python
# src/services/ai_chat_service.py
async def build_llm_context(
    self,
    db: AsyncSession,
    session_id: int,
    user_input: str,
    system_prompt: Optional[str] = None,
) -> List[dict]:
    """构建 LLM 消息列表（含历史摘要 + 最近消息）
    
    组装顺序（重要）:
    1. system prompt
    2. 历史摘要（1个）→ 长期记忆
    3. 近期摘要（最多3个，按时间顺序）→ 中期记忆
    4. 最近20条原始消息（按时间顺序）→ 短期记忆
    5. 当前用户输入
    """
    messages = []
    
    # 1. system prompt
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    
    # 2. 历史摘要（最多 1 个）
    archived = await AIChatRepository.list_summaries(
        db, session_id, is_archived=True, limit=1
    )
    if archived:
        s = archived[0]
        messages.append({
            "role": "system",
            "content": f"[历史背景 seq={s.start_seq}-{s.end_seq}] {s.summary}"
        })
    
    # 3. 近期摘要（最多 3 个，按 end_seq 升序）
    recent_summaries = await AIChatRepository.list_summaries(
        db, session_id, is_archived=False, order_by='end_seq ASC', limit=3
    )
    for s in recent_summaries:
        messages.append({
            "role": "system",
            "content": f"[近期摘要 seq={s.start_seq}-{s.end_seq}] {s.summary}"
        })
    
    # 4. 最近 20 条原始消息（按 seq 升序）
    recent_msgs = await AIChatRepository.list_recent_messages(db, session_id, limit=20)
    recent_msgs.reverse()  # 倒序 → 升序
    for msg in recent_msgs:
        role = "user" if msg.role == MessageRole.USER.value else "assistant"
        messages.append({"role": role, "content": msg.content})
    
    # 5. 当前用户输入
    messages.append({"role": "user", "content": user_input})
    
    return messages
```

### 7.2 上下文结构示例

```
seq=1-100 时，第 101 条消息的上下文:

┌────────────────────────────────────────────┐
│ [system] 你是智能助手...                    │
├────────────────────────────────────────────┤
│ [system] [历史背景 seq=1-50] 用户咨询了...  │  ← 历史摘要（合并自 1-20, 21-40）
├────────────────────────────────────────────┤
│ [system] [近期摘要 seq=51-70] 用户问...    │  ← 近期摘要 1
│ [system] [近期摘要 seq=71-90] 用户上传...  │  ← 近期摘要 2
│ [system] [近期摘要 seq=91-100] 用户确认... │  ← 近期摘要 3
├────────────────────────────────────────────┤
│ [user] seq=81                              │  ← 最近 20 条消息
│ [assistant] seq=82                         │
│ ...                                         │
│ [assistant] seq=100                        │
├────────────────────────────────────────────┤
│ [user] seq=101 (当前输入)                  │
└────────────────────────────────────────────┘
```

---

## 8. 接入点

### 8.1 在 `stream_chat` 中调用

```python
# src/services/ai_chat_service.py
async def stream_chat(self, db, user_id, user_input, session_id=None):
    # ... 获取或创建会话 ...
    
    # 1. 保存用户消息
    user_msg = await AIChatRepository.create_message(...)
    await db.flush()
    
    # 2. 检查并触发压缩（异步、不阻塞主流程）
    compress_service = get_compress_service()
    compressed = await compress_service.maybe_compress(db, current_session_id)
    if compressed:
        yield {
            "event": "context_compressed",
            "data": {"message": "已压缩历史上下文", "summaryId": compressed}
        }
    
    # 3. 构建上下文
    messages = await self.build_llm_context(db, current_session_id, user_input, system_prompt)
    
    # 4. 流式调用 LLM
    # ...
```

### 8.2 异步压缩（推荐）

压缩是 LLM 调用，可能耗时。建议：

```python
# 方案 A: 同步压缩（实现简单，但可能阻塞）
compressed = await compress_service.maybe_compress(db, session_id)

# 方案 B: 异步压缩（用 BackgroundTasks，不阻塞主对话）
from fastapi import BackgroundTasks
background_tasks.add_task(compress_service.maybe_compress, db, session_id)
```

**推荐方案 A**，简单可靠。LLM 摘要生成 < 3s，用户感知不明显。

---

## 9. 配置项（.env 导入）

所有压缩相关配置通过 `.env` 文件管理，启动时由 `pydantic-settings` 加载到 `src/infra/config.py`。

### 9.1 .env 配置

```bash
# .env
# ─── 会话压缩 ───
SUMMARY_COMPRESS_INTERVAL=20                  # 累计多少条消息触发一次压缩
SUMMARY_RECENT_MAX_COUNT=3                    # 近期摘要最大数量
SUMMARY_RECENT_MAX_CHARS=300                  # 近期摘要最大字符数
SUMMARY_ARCHIVED_MAX_CHARS=800                # 历史摘要最大字符数
SUMMARY_MERGE_TARGET_CHARS=800                # 历史摘要合并时目标字数
```

### 9.2 配置加载（src/infra/config.py）

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置: 从 .env 加载"""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ─── 会话压缩 ───
    summary_compress_interval: int = 20       # 对应 SUMMARY_COMPRESS_INTERVAL
    summary_recent_max_count: int = 3         # 对应 SUMMARY_RECENT_MAX_COUNT
    summary_recent_max_chars: int = 300       # 对应 SUMMARY_RECENT_MAX_CHARS
    summary_archived_max_chars: int = 800     # 对应 SUMMARY_ARCHIVED_MAX_CHARS
    summary_merge_target_chars: int = 800     # 对应 SUMMARY_MERGE_TARGET_CHARS


settings = Settings()
```

### 9.3 配置命名约定

| .env 变量名 | Python 字段 | 说明 |
|-------------|-------------|------|
| `SUMMARY_COMPRESS_INTERVAL` | `summary_compress_interval` | 压缩窗口（条） |
| `SUMMARY_RECENT_MAX_COUNT` | `summary_recent_max_count` | 近期摘要数量上限 |
| `SUMMARY_RECENT_MAX_CHARS` | `summary_recent_max_chars` | 近期摘要字数上限 |
| `SUMMARY_ARCHIVED_MAX_CHARS` | `summary_archived_max_chars` | 历史摘要字数上限 |
| `SUMMARY_MERGE_TARGET_CHARS` | `summary_merge_target_chars` | 合并后目标字数 |

```
命名规范:
- .env: SCREAMING_SNAKE_CASE (大写下划线)
- Python: snake_case (小写下划线)
- 前缀统一 SUMMARY_*, 便于运维一眼识别
```

### 9.4 在业务代码中使用

```python
from src.infra.config import settings


async def _generate_summary(messages: List[AgentMessage]) -> str:
    """生成近期摘要, 字数硬约束"""
    prompt = SUMMARY_PROMPT.format(
        max_chars=settings.summary_recent_max_chars,  # ← .env 注入
        messages_text=_format_messages(messages),
    )
    ...


async def _merge_oldest_to_archive(db, session_id):
    """合并最旧的近期到历史"""
    merged_text = await _merge_summary_texts(
        old_text=archive.summary,
        new_text=oldest.summary,
        target_chars=settings.summary_merge_target_chars,  # ← .env 注入
    )
    ...


def _check_should_compress(snapshot, latest_seq: int) -> bool:
    """判断是否触发压缩"""
    if snapshot is None:
        return latest_seq >= settings.summary_compress_interval  # ← .env 注入
    return (latest_seq - snapshot.last_summary_end_seq) >= settings.summary_compress_interval


async def _cleanup_excess_recent(db, session_id):
    """清理超额的近期摘要"""
    all_recent = await get_recent_summaries(db, session_id)
    max_count = settings.summary_recent_max_count  # ← .env 注入
    while len(all_recent) > max_count:
        await _merge_oldest_to_archive(db, session_id)
        all_recent = await get_recent_summaries(db, session_id)
```

### 9.5 整体大小恒定验证

```
会话进行 N 次压缩后, 上下文中的摘要 token:
- 历史摘要:  ≤ summary_archived_max_chars 字 (固定)
- 近期摘要:  summary_recent_max_count × summary_recent_max_chars 字 (固定)
- 总摘要 token 与对话长度无关, 永远恒定 ✅

LLM 单次调用 token 估算 (字符转 token 按 1:1.8):
- 历史: 800 字 ≈ 445 token
- 近期: 3 × 300 = 900 字 ≈ 500 token
- 总摘要: ≈ 945 token

加上:
- system prompt: ≈ 500 token
- 最近 20 条消息: ≈ 2000 token
- 当前输入: ≈ 200 token
- LLM 输出: ≈ 500 token
────────────────────────────────────
- 合计: ≈ 4145 token, 远低于 8K 限制
```

---

## 9.6 摘要大小限制策略（三道防线）

> **详细策略说明**: 三道防线（生成硬约束 / 合并时检查 / 超阈值再压缩）已在第 5 节实现，本节说明设计原理。

```
┌─────────────────────────────────────────────────────────────────┐
│  第一道: 生成时硬约束                                            │
│  - LLM prompt 明确要求"不超过 X 字"                              │
│  - 近期摘要 ≤ summary_recent_max_chars 字                        │
│  - 历史摘要合并 ≤ summary_merge_target_chars 字                 │
├─────────────────────────────────────────────────────────────────┤
│  第二道: 合并时检查                                              │
│  - 合并两条历史摘要时, LLM 输出固定 ≤ 目标字数                    │
│  - 避免历史摘要无限制膨胀                                        │
├─────────────────────────────────────────────────────────────────┤
│  第三道: 超阈值再压缩                                            │
│  - 历史摘要 > summary_archived_max_chars 字时, 触发"再压缩"      │
│  - 用 LLM 把超长摘要压缩到 ≤ 目标字数                            │
└─────────────────────────────────────────────────────────────────┘
```

### 9.6.1 字符数 vs Token 数

```
选择"字符数"作为限制单位的原因:
- 中英文混合场景下, 字符数更稳定可控
- token 数依赖分词器, 不同模型差异大
- 字符数与 token 数的经验比例: 1 token ≈ 1.5~2 字符 (中文)

实际配置:
- 近期摘要 300 字 ≈ 150~200 token
- 历史摘要 800 字 ≈ 400~550 token

LLM 单次调用 token 限制 8K~32K, 远远足够
```

### 9.6.2 合并 prompt（参考）

```python
# 合并两条历史摘要
MERGE_PROMPT = """请将以下两段历史摘要合并为一段精炼摘要。

要求：
- 总字数不超过 {target_chars} 字
- 保留所有关键信息: 用户意图、事实、决定、待办
- 去除重复描述

摘要A (较早):
{a_text}

摘要B (较新):
{b_text}

合并后的摘要:"""

# 超出阈值再压缩
RESUMMARIZE_PROMPT = """以下历史摘要过长，请重新压缩。

要求：
- 总字数不超过 {target_chars} 字
- 保留关键信息, 舍弃次要细节

当前摘要:
{text}

压缩后的摘要:"""
```

---

## 10. 数据库迁移

### 10.1 迁移脚本

```python
# src/scripts/migrate_step3_compress.py

ALTER_SQLS = [
    # 1. 删除旧字段
    "ALTER TABLE agent_session_snapshots DROP COLUMN IF EXISTS message_count;",
    "ALTER TABLE agent_session_snapshots DROP COLUMN IF EXISTS last_message_at;",
    "ALTER TABLE agent_session_snapshots DROP COLUMN IF EXISTS needs_compress;",
    # total_message_count 不在旧表里，但保险起见也删
    "ALTER TABLE agent_session_snapshots DROP COLUMN IF EXISTS total_message_count;",
    
    # 2. 新增字段到 snapshot
    """
    ALTER TABLE agent_session_snapshots
    ADD COLUMN IF NOT EXISTS last_summary_end_seq INTEGER NOT NULL DEFAULT 0;
    """,
    """
    ALTER TABLE agent_session_snapshots
    ADD COLUMN IF NOT EXISTS recent_summary_count INTEGER NOT NULL DEFAULT 0;
    """,
    """
    ALTER TABLE agent_session_snapshots
    ADD COLUMN IF NOT EXISTS last_summary_at TIMESTAMP WITH TIME ZONE;
    """,
    """
    ALTER TABLE agent_session_snapshots
    ADD COLUMN IF NOT EXISTS total_summary_count INTEGER NOT NULL DEFAULT 0;
    """,
    
    # 3. 新增字段到 summary
    """
    ALTER TABLE agent_session_summaries
    ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT FALSE;
    """,
    
    # 4. 新增索引
    """
    CREATE INDEX IF NOT EXISTS idx_agent_session_summaries_archived
    ON agent_session_summaries(session_id, is_archived, end_seq);
    """,
]
```

### 10.2 执行方式

```bash
cd idbackend
python -m src.scripts.migrate_step3_compress
```

---

## 11. 验收清单

- [ ] **数据模型**：
  - [ ] `agent_session_snapshots` 字段更新（新增 4 个：无 total_message_count，删除 4 个）
  - [ ] `agent_session_summaries` 新增 `is_archived` 字段
  - [ ] 索引 `idx_agent_session_summaries_archived` 创建
- [ ] **Repository 层**：
  - [ ] `get_snapshot` / `upsert_snapshot` 实现
  - [ ] `list_summaries` 支持 `is_archived` 过滤
  - [ ] `get_latest_seq` / `get_messages_range` 实现
- [ ] **Service 层**：
  - [ ] `CompressService.maybe_compress()` 实现
  - [ ] `_merge_oldest_to_archive()` 实现
  - [ ] `build_llm_context` 重构为新结构
- [ ] **触发逻辑**：
  - [ ] 第 21 条消息后不触发（差值 = 1）
  - [ ] 第 40 条消息后触发（差值 = 20）
  - [ ] 触发后 snapshot.last_summary_end_seq 更新
- [ ] **合并逻辑**：
  - [ ] 近期摘要 = 4 时，最旧的合并到历史
  - [ ] 合并后近期 = 3，历史 = 1
- [ ] **SSE 事件**：
  - [ ] `context_compressed` 事件正确发出
- [ ] **端到端测试**：
  - [ ] 模拟 100 条消息，验证 snapshot / summary 状态正确

---

## 12. 与 daily.md 的对齐

| daily.md 描述 | 本文档实现 |
|--------------|----------|
| 每20条消息压缩一次 | ✅ `SUMMARY_COMPRESS_INTERVAL=20`（.env 注入） |
| 最近20条消息 + 3个近期摘要 | ✅ `build_llm_context` 第 4、3 步 |
| 最近摘要设置最大数量3 | ✅ `SUMMARY_RECENT_MAX_COUNT=3`（.env 注入） |
| 旧摘要合并到历史摘要 | ✅ `_merge_oldest_to_archive` |
| 用一个 session 表记录 | ❌ 改用 snapshot 表，职责更清晰 |
| session_summary 区别历史/近期 | ✅ `is_archived` 字段 |
| 摘要大小可控 | ✅ `SUMMARY_*_MAX_CHARS` 系列（.env 注入） |

---

## 13. 文档索引

| 文档 | 内容 |
|------|------|
| [00-overview.md](./00-overview.md) | Agent 总体方案 |
| [04-api-sse.md](./04-api-sse.md) | Step 4 SSE 接口（包含旧版压缩占位） |
| 本文档 | Step 3 专题：上下文压缩与摘要合并详细设计 |