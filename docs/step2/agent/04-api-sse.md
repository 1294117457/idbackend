# Step 4 · FastAPI SSE 接口与持久化

> 本步目标：写 3 个路由文件（agent.py / conversation.py / knowledge.py），完整定义 Request/Response schema，实现 SSE 流式接口和会话持久化。

---

## 1. 任务清单

| # | 任务 | 文件 | 关键点 |
|---|------|------|--------|
| 4.1 | agent schema | src/app/schemas/agent.py | StreamRequest / ResumeRequest |
| 4.2 | agent SSE 路由 | src/app/routes/agent.py | StreamingResponse |
| 4.3 | conversation 路由 | src/app/routes/conversation.py | CRUD 会话 |
| 4.4 | knowledge schema | src/app/schemas/policy.py | KB CRUD |
| 4.5 | 上下文压缩 | agent_service.py | CONTEXT_MAX_MESSAGES |

---

## 2. SSE 事件类型

| type | 时机 | data |
|------|------|------|
| token | LLM 输出 | {content} |
| interrupt | graph.interrupt() | {type, question, suggestions?} |
| result | 子图结束 | {reply?, readyForStep2?, templateId?} |
| error | 异常 | {message} |
| session | 流开始 | {sessionId} |
| context_compressed | 压缩 | {message, beforeCount, afterCount} |

---
## 3. agent schema

```python
# src/app/schemas/agent.py
from pydantic import BaseModel, Field
from typing import Optional

class StreamRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    sessionId: str = Field(..., min_length=1, max_length=64)
    intent: Optional[str] = Field(None)

class ResumeRequest(BaseModel):
    sessionId: str
    supplement: str
    uploadedFileId: Optional[int] = None
    uploadedText: Optional[str] = None
    selectedTemplateId: Optional[int] = None
    selectedRuleId: Optional[int] = None

class AgentResultVO(BaseModel):
    reply: Optional[str] = None
    readyForStep2: bool = False
    templateId: Optional[int] = None
    prefilledSelections: Optional[dict] = None
    message: Optional[str] = None
```

## 4. agent 路由

```python
# src/app/routes/agent.py
from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from src.app.dependencies import get_db
from src.agent.agent_service import AgentService
import json, asyncio

router = APIRouter(prefix='/ai/agent', tags=['AI Agent'])
_svc = AgentService()

@router.post('/stream')
async def stream(
    message: str = Depends(lambda: None),
    sessionId: str = Depends(lambda: None),
    intent: str = Depends(lambda: None),
    file: UploadFile = File(None),
    db: AsyncSession = Depends(get_db),
):
    async def gen():
        async for ev in _svc.stream_chat(
            message=message or '', user_id=0, session_id=sessionId or 'default', db=db
        ):
            yield 'data: ' + json.dumps(ev, ensure_ascii=False) + '

'
        yield 'data: [DONE]

'
    return StreamingResponse(gen(), media_type='text/event-stream')
```

## 5. conversation 路由

CRUD 会话持久化：POST /ai/conversation/create, GET /ai/conversation/list, GET /ai/conversation/{sessionId}/messages, DELETE /ai/conversation/{sessionId}/messages

### conversation schema
```python
# src/app/schemas/conversation.py
class CreateConversationRequest(BaseModel):
    firstMessage: Optional[str] = None
class ConversationVO(BaseModel):
    id: int
    sessionId: str
    title: str
    messageCount: int
    lastMessage: Optional[str]
    createdAt: str
class MessageRecordVO(BaseModel):
    id: int
    role: str  # user/assistant
    content: str
    createdAt: str
```

### conversation route
```python
# src/app/routes/conversation.py
router = APIRouter(prefix='/ai/conversation', tags=['AI Conversation'])
@router.post('/create')  # create new session
@router.get('/list')     # list user sessions
@router.get('/sessionId}/messages')  # get history
@router.delete('/sessionId}/messages') # clear history
```

## 6. 上下文压缩

超过 CONTEXT_MAX_MESSAGES 时，用 LLM 做摘要压缩，丢弃旧消息，保留摘要。

```python
# src/agent/graph/agent_service.py
async def _maybe_compress(self, messages):
    if len(messages) > _settings.CONTEXT_MAX_MESSAGES:
        # 1) summarize old messages
        # 2) replace old messages with single summary message
        # yield context_compressed event
        pass
```

## 7. 下一步

进入 05-frontend-ui.md 实现前端浮窗组件和 TemplateApplyDialog 集成。
