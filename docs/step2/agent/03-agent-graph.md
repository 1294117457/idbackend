# Step 3 · LangGraph Agent 实现

> 本步目标：**重写 `src/agent/` 目录**，用 LangGraph 编排 intent 分类 + consult 子图 + apply 子图，用 `interrupt` 等待用户上传和选择，把工具函数接到现有 Service 层。
> 本步**不**写 FastAPI 路由（留给 Step 4），只产出 `agent/` 包内部代码。

---

## 1. 现状问题

| 模块 | 问题 |
|------|------|
| `graph/builder.py` | 4 个简单节点串联，没有 `interrupt`，没有 subgraph |
| `nodes/classify/classify_node.py` | 用关键词匹配，意图不准 |
| `nodes/consult/answer_node.py` | TODO，假装回答 |
| `nodes/apply/submit_node.py` | TODO，假装提交 |
| `nodes/apply/confirm_node.py` | TODO，假装成功 |
| `tools/__init__.py` | 字段名错（`get_templates_tool` 用 `t.template_name`，但 ORM 是 `name`），`create_application_tool` 缺 `category_id / proof_score / proofList` |
| `state/__init__.py` | 字段不全，没有 `ApplyState` 的 `step` / `suggestions` / `frontend_payload` |

---

## 2. 任务清单

| # | 任务 | 文件 | 关键点 |
|---|------|------|--------|
| 3.1 | 重写 `MainState` / `ApplyState` / `ConsultState` | `src/agent/state/__init__.py` | 字段统一 + TypedDict 完整 |
| 3.2 | 重写 `classify_node` | `src/agent/nodes/classify/classify_node.py` | LLM 分类，few-shot |
| 3.3 | 实现 `consult_subgraph`（rag_retrieve + llm_answer） | `src/agent/nodes/consult/{retrieve,answer}_node.py` | 调 `rag/search.hybrid_search_policy` |
| 3.4 | 实现 `apply_subgraph`（gather / fetch_templates / ask_proof / rag_match / llm_rank / select_template / redirect） | `src/agent/nodes/apply/*.py` | interrupt 用法 |
| 3.5 | 重写 `tools/__init__.py` | `src/agent/tools/__init__.py` | 修正字段名 + 完整参数 |
| 3.6 | 挂 `template_indexer` 到 `TemplateService` | `src/services/template_service.py` | 异步 / 后台 task |
| 3.7 | 重写 `AgentGraph` / `AgentService` | `src/agent/graph/{builder,agent_service}.py` | 用 `astream_events` + interrupt 持久化 |

---

## 3. 详细设计

### 3.1 State 重写 `src/agent/state/__init__.py`

```python
"""LangGraph 状态定义"""
from typing import TypedDict, List, Literal, Optional, Any


class Message(TypedDict):
    role: Literal["user", "assistant", "system"]
    content: str
    metadata: Optional[dict]


class BaseState(TypedDict, total=False):
    """所有子图共享的基础字段"""
    messages: List[Message]
    user_id: int
    session_id: str
    error: Optional[str]


class ConsultState(BaseState):
    """咨询子图状态"""
    query: str
    retrieved_docs: Optional[List[dict]]
    answer: Optional[str]


# Apply 子图的 step 状态机
ApplyStep = Literal[
    "init",            # 入口
    "gathering",       # gather_user_info
    "fetching",        # fetch_templates
    "wait_proof",      # interrupt: 等用户上传 / 描述
    "matching",        # rag_match
    "ranking",         # llm_rank
    "wait_choice",     # interrupt: 等用户选 template
    "redirecting",     # redirect_to_apply
    "done",            # 终态
]


class ApplyState(BaseState):
    """申请子图状态"""
    step: ApplyStep

    # 用户侧输入
    uploaded_file_id: Optional[int]
    uploaded_text: Optional[str]          # OCR 出的纯文本
    user_supplement: Optional[str]        # 用户在 interrupt 时补充的对话内容

    # 内部数据
    user_info: Optional[dict]             # gather_user_info 结果
    template_candidates: List[dict]       # fetch_templates 结果（含 rules/attributes）
    rag_chunks: List[dict]                # rag_match 召回的 policy + template 片段
    suggestions: List[dict]               # llm_rank 输出的 Top-N
    prefilled_selections: dict            # 给前端的预填：{groupCode: attributeId}

    # 终态输出
    selected_template_id: Optional[int]
    frontend_payload: Optional[dict]      # {templateId, readyForStep2, prefilled}


# 顶层入口
MainState = BaseState
```

### 3.2 重写 `classify_node`

```python
"""意图分类节点（LLM 分类）"""
from typing import Literal
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from src.agent.state import MainState
from src.infra.config import get_settings

_settings = get_settings()

_CLASSIFY_PROMPT = """你是意图分类器。根据用户最后一句话，把意图分到 consult / apply / other 三类。

- consult: 用户在问政策、规则、怎么算、流程等（"怎么申请校三好"、"CET-6 加多少分"、"综测公式"）
- apply: 用户想要提交申请、上传材料、找合适的模板（"我要申请校三好"、"我有竞赛证书"、"帮我匹配模板"）
- other: 寒暄、问候、闲聊，或意图不清楚

只输出一个词：consult / apply / other。

用户消息：{query}
"""


async def classify_node(state: MainState) -> dict:
    messages = state.get("messages") or []
    if not messages:
        return {"error": "empty messages"}

    last = messages[-1].get("content", "") if isinstance(messages[-1], dict) else ""

    llm = ChatOpenAI(
        api_key=_settings.QWEN3_API_KEY,
        base_url=_settings.QWEN_BASE_URL,
        model=_settings.QWEN_CHAT_MODEL,
        temperature=0,
    )
    resp = await llm.ainvoke([
        SystemMessage(content=_CLASSIFY_PROMPT.format(query=last)),
    ])
    intent = (resp.content or "").strip().lower()
    if intent not in ("consult", "apply"):
        intent = "other"
    return {"intent": intent}
```

### 3.3 consult 子图

#### `src/agent/nodes/consult/retrieve_node.py`

```python
"""RAG 检索节点"""
from agent.state import ConsultState
from src.rag.search import hybrid_search_policy


async def retrieve_node(state: ConsultState) -> dict:
    db = state["_db"]  # 详见 3.7：在 builder 里通过 config 注入
    docs = await hybrid_search_policy(db, state["query"], top_k=5)
    return {"retrieved_docs": docs}
```

#### `src/agent/nodes/consult/answer_node.py`

```python
"""LLM 回答节点"""
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from agent.state import ConsultState
from src.infra.config import get_settings

_settings = get_settings()

_ANSWER_PROMPT = """你是学校的政策助手。基于【检索到的政策片段】回答用户问题。
要求：
- 只用提供的片段回答，不要编造
- 引用时用 [片段1][片段2] 标注
- 答不出来就说"这个问题当前知识库没有覆盖"

【检索到的政策片段】
{context}

【用户问题】
{query}
"""


async def answer_node(state: ConsultState) -> dict:
    docs = state.get("retrieved_docs") or []
    context_parts = [
        f"[片段{i+1}] {d.get('title','')}\n{d.get('content','')}"
        for i, d in enumerate(docs)
    ]
    context = "\n\n".join(context_parts) or "（无相关政策）"

    llm = ChatOpenAI(
        api_key=_settings.QWEN3_API_KEY,
        base_url=_settings.QWEN_BASE_URL,
        model=_settings.QWEN_CHAT_MODEL,
        temperature=_settings.AGENT_TEMPERATURE,
    )
    resp = await llm.ainvoke([
        SystemMessage(content=_ANSWER_PROMPT.format(context=context, query=state["query"])),
    ])
    return {"answer": resp.content or ""}
```

### 3.4 apply 子图

#### 节点概览

```
                 ┌──────────────────┐
                 │ gather_user_info │   读 user 表 + extra_info
                 └────────┬─────────┘
                          ▼
                 ┌──────────────────┐
                 │ fetch_templates  │   /api/bonus-template/list
                 └────────┬─────────┘
                          ▼
       ┌────────────[interrupt]─────────────┐
       │ wait_proof_input（等用户上传/描述）    │
       └────────────[resume]────────────────┘
                          ▼
                 ┌──────────────────┐
                 │ rag_match        │   混合检索 policy + template_embedding
                 └────────┬─────────┘
                          ▼
                 ┌──────────────────┐
                 │ llm_rank         │   LLM 输出 Top-N suggestions
                 └────────┬─────────┘
                          ▼
       ┌────────────[interrupt]─────────────┐
       │ wait_user_choice（等用户选 template）│
       └────────────[resume]────────────────┘
                          ▼
                 ┌──────────────────────┐
                 │ redirect_to_apply    │   生成 frontend_payload
                 └──────────────────────┘
```

#### `gather_user_info_node.py`

```python
from agent.state import ApplyState
from agent.tools import get_user_info_tool


async def gather_user_info_node(state: ApplyState) -> dict:
    db = state["_db"]
    info = await get_user_info_tool(db, state["user_id"])
    return {"user_info": info, "step": "gathering"}
```

#### `fetch_templates_node.py`

```python
from agent.state import ApplyState
from agent.tools import get_active_templates_with_rules


async def fetch_templates_node(state: ApplyState) -> dict:
    """拉所有 is_active=True 的 template，每个带 rules + attributes"""
    db = state["_db"]
    templates = await get_active_templates_with_rules(db)
    return {"template_candidates": templates, "step": "fetching"}
```

#### `ask_proof_node.py`（interrupt #1）

```python
"""第一次 interrupt：等用户上传证明材料 / 补充描述"""
from langgraph.prebuilt import interrupt

from agent.state import ApplyState


async def ask_proof_node(state: ApplyState) -> dict:
    # 把"我们准备好接收材料"的信号抛给前端
    interrupt_payload = {
        "type": "upload_proof",
        "question": "请上传您的证明材料（如证书 PDF/图片），或用文字描述您的情况（如：拿了校三好、CET-6 500 分）。",
        "requireFiles": True,
    }
    user_input = interrupt(interrupt_payload)
    # user_input = {"file_id": int, "text": str}  from resume
    return {
        "uploaded_file_id": user_input.get("file_id"),
        "uploaded_text": user_input.get("text"),
        "user_supplement": user_input.get("text"),
        "step": "wait_proof",
    }
```

#### `rag_match_node.py`

```python
"""混合检索：policy_documents + template_embeddings"""
from agent.state import ApplyState
from src.rag.search import hybrid_search_policy, hybrid_search_templates


async def rag_match_node(state: ApplyState) -> dict:
    db = state["_db"]
    query = state.get("uploaded_text") or state.get("user_supplement") or ""
    if not query.strip():
        return {"rag_chunks": {"policy": [], "templates": []}, "step": "matching"}

    policy_hits = await hybrid_search_policy(db, query, top_k=5)
    template_hits = await hybrid_search_templates(db, query, top_k=5)
    return {
        "rag_chunks": {"policy": policy_hits, "templates": template_hits},
        "step": "matching",
    }
```

#### `llm_rank_node.py`

```python
"""LLM 排序：用 JSON Schema 强制结构化输出"""
import json
from typing import List
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field

from agent.state import ApplyState
from src.infra.config import get_settings

_settings = get_settings()


class Suggestion(BaseModel):
    templateId: int
    templateName: str
    ruleId: int = Field(..., description="最匹配的 rule id")
    ruleName: str
    estimatedScore: float = Field(..., description="预估可加分数")
    reason: str = Field(..., description="匹配理由，1~2 句话")


class RankResult(BaseModel):
    suggestions: List[Suggestion] = Field(..., max_length=5, min_length=1)


_RANK_PROMPT = """你是申请匹配助手。基于【用户情况】+【政策片段】+【候选模板（含 rules）】，
从候选模板里挑出 1~5 个最匹配的，按可能性从高到低排序。

要求：
- 只输出 JSON，遵守给定的 schema
- estimatedScore 不要超过 template.maxScore
- reason 要结合用户的实际证据（不能凭空夸）
- 没有合适的就 suggestions=[]，不要瞎编

【用户情况】
{user_info}

【用户原始材料文本】
{user_text}

【政策片段】
{policy_chunks}

【候选模板】
{template_candidates}

输出 JSON：
"""


async def llm_rank_node(state: ApplyState) -> dict:
    candidates = state.get("template_candidates") or []
    # 序列化（避免太长）
    cand_text = json.dumps(
        [
            {
                "id": t["id"], "name": t["name"], "maxScore": t["maxScore"],
                "rules": [
                    {"id": r["id"], "name": r["name"], "type": r["type"],
                     "attributes": [{"id": a["id"], "name": a["name"], "value": a.get("value","")} for a in r["attributes"]]}
                    for r in t.get("rules", [])
                ],
            }
            for t in candidates[:30]   # 限 30 防止 prompt 爆
        ],
        ensure_ascii=False,
    )
    policy_chunks = state.get("rag_chunks", {}).get("policy", [])
    pol_text = "\n\n".join(
        f"[{p.get('title','')}] {p.get('content','')[:500]}" for p in policy_chunks
    )

    llm = ChatOpenAI(
        api_key=_settings.QWEN3_API_KEY,
        base_url=_settings.QWEN_BASE_URL,
        model=_settings.QWEN_CHAT_MODEL,
        temperature=_settings.AGENT_TEMPERATURE,
        model_kwargs={"response_format": {"type": "json_object"}},
    )
    structured = llm.with_structured_output(RankResult)
    resp = await structured.ainvoke([
        SystemMessage(content=_RANK_PROMPT.format(
            user_info=json.dumps(state.get("user_info", {}), ensure_ascii=False),
            user_text=state.get("uploaded_text", ""),
            policy_chunks=pol_text or "（无）",
            template_candidates=cand_text,
        )),
    ])
    return {"suggestions": [s.model_dump() for s in resp.suggestions], "step": "ranking"}
```

#### `select_template_node.py`（interrupt #2）

```python
"""第二次 interrupt：等用户从候选列表中选 1 个"""
from langgraph.prebuilt import interrupt

from agent.state import ApplyState


async def select_template_node(state: ApplyState) -> dict:
    suggestions = state.get("suggestions") or []
    if not suggestions:
        # 没匹配上，直接结束，让前端给出友好提示
        return {"selected_template_id": None, "step": "done"}

    interrupt_payload = {
        "type": "select_template",
        "question": "根据您提供的信息，我为您匹配到以下模板，请选择最合适的一个：",
        "suggestions": suggestions,
    }
    user_choice = interrupt(interrupt_payload)
    # user_choice = {"templateId": int, "ruleId": int}
    selected_id = user_choice.get("templateId")
    return {
        "selected_template_id": selected_id,
        "step": "wait_choice",
    }
```

#### `redirect_to_apply_node.py`

```python
"""构造给前端的 payload：模板 id + 预填选项 + 跳 Step 2 指令"""
from agent.state import ApplyState
from agent.tools import build_prefill_for_template


async def redirect_to_apply_node(state: ApplyState) -> dict:
    selected_id = state.get("selected_template_id")
    if not selected_id:
        return {
            "frontend_payload": {
                "readyForStep2": False,
                "message": "未匹配到合适模板，您可以浏览全部模板列表。",
            },
            "step": "done",
        }

    # 根据 candidate + 用户信息，算出哪些 attribute 可以预填
    tpl = next((t for t in state.get("template_candidates", []) if t["id"] == selected_id), None)
    prefill = build_prefill_for_template(tpl, state.get("user_info") or {})
    return {
        "frontend_payload": {
            "readyForStep2": True,
            "templateId": selected_id,
            "prefilledSelections": prefill,
        },
        "step": "done",
    }
```

### 3.5 重写 `tools/__init__.py`

修正字段名错误，补充参数：

```python
"""Agent 工具 - 直接调用 Service / Repository 层"""
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.user_service import UserService
from src.services.template_service import TemplateService
from src.services.application_service import ApplicationService
from src.models.user import User


async def get_user_info_tool(db: AsyncSession, user_id: int) -> dict:
    """获取用户基本信息"""
    user = await UserService.get_user_by_id(db, user_id)
    if not user:
        return {"error": "用户不存在"}
    return {
        "userId": user.id,
        "username": user.username,
        "fullName": user.full_name,
        "studentId": User.extract_student_id(user.username),
        "major": user.major,
        "grade": user.grade,
        "enrollmentYear": user.enrollment_year,
        "graduationYear": user.graduation_year,
        "phone": user.phone,
    }


async def get_user_extra_info_tool(db: AsyncSession, user_id: int) -> dict:
    """获取学生扩展字段值"""
    user = await UserService.get_user_by_id(db, user_id)
    return user.extra_info if user else {}


async def get_active_templates_with_rules(db: AsyncSession) -> List[dict]:
    """获取所有 active 模板（含 rules + attributes）"""
    templates = await TemplateService.list_active_with_rules(db)
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "maxScore": float(t.max_score) if t.max_score else 0,
            "categoryId": t.category_id,
            "rules": [
                {
                    "id": r.id,
                    "name": r.name,
                    "type": r.type.value if hasattr(r.type, "value") else r.type,
                    "score": float(r.score) if r.score else 0,
                    "attributes": [
                        {
                            "id": a.id,
                            "name": a.name,
                            "groupCode": a.group_code,
                            "groupName": a.group_name,
                            "value": a.value or "",
                            "inputMin": float(a.input_min) if a.input_min is not None else None,
                            "inputMax": float(a.input_max) if a.input_max is not None else None,
                        }
                        for a in r.attributes
                    ],
                }
                for r in (t.rules or [])
            ],
        }
        for t in templates
    ]


async def search_templates_tool(
    db: AsyncSession,
    query: str,
    top_k: int = 5,
) -> List[dict]:
    """向量 + 关键词混合检索 template"""
    from src.rag.search import hybrid_search_templates
    return await hybrid_search_templates(db, query, top_k=top_k)


async def search_policies_tool(
    db: AsyncSession,
    query: str,
    top_k: int = 5,
) -> List[dict]:
    """检索政策片段"""
    from src.rag.search import hybrid_search_policy
    return await hybrid_search_policy(db, query, top_k=top_k)


def build_prefill_for_template(template: dict, user_info: dict) -> Dict[str, Any]:
    """根据用户已知信息预填 template attribute

    简化版：只处理 groupCode == 'MAJOR'/'GRADE' 之类已知字段。
    复杂场景可以让 llm_rank 阶段直接产出预填建议。
    """
    if not template:
        return {}
    prefill = {}
    user_major = user_info.get("major")
    user_grade = user_info.get("grade")

    for rule in template.get("rules", []):
        for attr in rule.get("attributes", []):
            gc = attr.get("groupCode", "")
            if gc == "MAJOR" and user_major:
                # attribute.name == user_major 时预填
                if user_major in attr.get("name", ""):
                    prefill[gc] = attr["id"]
            if gc == "GRADE" and user_grade:
                # attribute.value 含 grade 数字时预填
                if str(user_grade) in attr.get("value", ""):
                    prefill[gc] = attr["id"]
    return prefill


# ⚠️ 不要暴露 create_application_tool 给 LLM：
# proofScore / proofList 是用户填的，不该 agent 自动提交。
# 真正创建申请由用户在 TemplateApplyDialog 的 Step 2 手动完成。
```

> ⚠️ **删除** 现有 `create_application_tool`、`get_user_scores_tool` 等会越权操作的工具。学生只能"选 template + 预填"，不能直接"提交申请"。

### 3.6 挂 template_indexer 到 TemplateService

`src/services/template_service.py` 的 `create / update / save_template` 方法末尾追加：

```python
import asyncio
from src.rag.template_indexer import reindex_template

# 在 create() commit 之后：
async def _schedule_reindex(template_id: int):
    """后台异步重建索引，不阻塞请求"""
    from src.infra.database import async_session_factory
    async def _run():
        async with async_session_factory() as db:
            try:
                await reindex_template(db, template_id)
            except Exception as e:
                logger.exception("reindex template %s failed", template_id)
    asyncio.create_task(_run())

# create / update / save_template / delete_template 后都调用：
await _schedule_reindex(template.id)
```

### 3.7 重写 `builder.py` 和 `agent_service.py`

#### `src/agent/graph/builder.py`

```python
"""LangGraph Agent Builder"""
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agent.state import MainState, ConsultState, ApplyState
from agent.nodes.classify import classify_node
from agent.nodes.consult import retrieve_node, answer_node
from agent.nodes.apply import (
    gather_user_info_node,
    fetch_templates_node,
    ask_proof_node,
    rag_match_node,
    llm_rank_node,
    select_template_node,
    redirect_to_apply_node,
)


def _route_intent(state: MainState) -> str:
    return state.get("intent") or "other"


def build_main_graph(checkpointer):
    """主图：classify → consult/apply/other"""
    g = StateGraph(MainState)
    g.add_node("classify", classify_node)
    g.add_node("consult_subgraph", build_consult_subgraph(checkpointer).compile())
    g.add_node("apply_subgraph", build_apply_subgraph(checkpointer).compile())
    g.add_node("unknown_handler", lambda s: {"answer": "我没太明白您的意思，可以换个说法吗？"})

    g.set_entry_point("classify")
    g.add_conditional_edges(
        "classify",
        _route_intent,
        {
            "consult": "consult_subgraph",
            "apply": "apply_subgraph",
            "other": "unknown_handler",
        },
    )
    g.add_edge("consult_subgraph", END)
    g.add_edge("apply_subgraph", END)
    g.add_edge("unknown_handler", END)
    return g.compile(checkpointer=checkpointer)


def build_consult_subgraph(checkpointer):
    g = StateGraph(ConsultState)
    g.add_node("retrieve", retrieve_node)
    g.add_node("answer", answer_node)
    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "answer")
    g.add_edge("answer", END)
    return g


def build_apply_subgraph(checkpointer):
    g = StateGraph(ApplyState)
    g.add_node("gather", gather_user_info_node)
    g.add_node("fetch_tpl", fetch_templates_node)
    g.add_node("ask_proof", ask_proof_node)
    g.add_node("rag_match", rag_match_node)
    g.add_node("llm_rank", llm_rank_node)
    g.add_node("select", select_template_node)
    g.add_node("redirect", redirect_to_apply_node)

    g.set_entry_point("gather")
    g.add_edge("gather", "fetch_tpl")
    g.add_edge("fetch_tpl", "ask_proof")
    g.add_edge("ask_proof", "rag_match")
    g.add_edge("rag_match", "llm_rank")
    g.add_edge("llm_rank", "select")
    g.add_edge("select", "redirect")
    g.add_edge("redirect", END)
    return g


class AgentGraphManager:
    """Agent 图管理器（单例）"""
    _instance: "AgentGraphManager | None" = None

    def __init__(self):
        # 短期用 MemorySaver 即可；生产建议 PostgresSaver
        # from src.infra.config import get_settings
        # self.checkpointer = AsyncPostgresSaver.from_conn_string(get_settings().DATABASE_URL)
        self.checkpointer = MemorySaver()
        self.graph = build_main_graph(self.checkpointer)

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
```

#### `src/agent/graph/agent_service.py`

```python
"""Agent Service：包装 graph 调用，对接 SSE"""
import json
from typing import AsyncGenerator, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from agent.graph.builder import AgentGraphManager
from src.infra.database import async_session_factory


class AgentService:
    """Agent 服务入口"""

    def __init__(self):
        self.mgr = AgentGraphManager.instance()
        self.graph = self.mgr.graph

    def _initial_state(self, user_id: int, session_id: str, message: str) -> dict:
        return {
            "messages": [{"role": "user", "content": message}],
            "user_id": user_id,
            "session_id": session_id,
            # 子图专属字段给默认值
            "_db": None,   # 见下：在 stream 前注入
        }

    async def stream_chat(
        self,
        *,
        message: str,
        user_id: int,
        session_id: str,
        db: AsyncSession,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """SSE 入口：astream_events 转 SSE 事件"""
        config = {"configurable": {"thread_id": session_id}}
        initial = self._initial_state(user_id, session_id, message)
        initial["_db"] = db

        # 先 yield session_id，前端建立关联
        yield {"type": "session", "data": {"sessionId": session_id}}

        try:
            async for event in self.graph.astream_events(initial, config=config, version="v2"):
                kind = event.get("event")
                name = event.get("name", "")

                if kind == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    if chunk and getattr(chunk, "content", None):
                        yield {"type": "token", "data": {"content": chunk.content}}

                elif kind == "on_interrupt":
                    interrupt_data = event["data"].get("__interrupt__", [])
                    if interrupt_data:
                        payload = interrupt_data[0].value if hasattr(interrupt_data[0], "value") else interrupt_data[0]
                        yield {"type": "interrupt", "data": payload}

                elif kind == "on_chain_end" and name in ("apply_subgraph", "consult_subgraph", "unknown_handler"):
                    output = event["data"].get("output", {})
                    if "frontend_payload" in output:
                        yield {"type": "result", "data": output["frontend_payload"]}
                    elif "answer" in output:
                        yield {"type": "result", "data": {"reply": output["answer"]}}
        except Exception as e:
            yield {"type": "error", "data": {"message": str(e)}}

    async def resume(
        self,
        *,
        session_id: str,
        user_input: dict,
        db: AsyncSession,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """恢复 interrupt：调用 Command(resume=...)"""
        from langgraph.types import Command
        config = {"configurable": {"thread_id": session_id}}
        # 注入 db：langgraph 不会自动传 _db，需要通过 RunnableConfig 透传
        async for event in self.graph.astream_events(
            Command(resume=user_input),
            config=config,
            version="v2",
        ):
            kind = event.get("event")
            if kind == "on_chain_end":
                output = event["data"].get("output", {})
                if "frontend_payload" in output:
                    yield {"type": "result", "data": output["frontend_payload"]}
            elif kind == "on_interrupt":
                interrupt_data = event["data"].get("__interrupt__", [])
                if interrupt_data:
                    payload = interrupt_data[0].value if hasattr(interrupt_data[0], "value") else interrupt_data[0]
                    yield {"type": "interrupt", "data": payload}
            elif kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if chunk and getattr(chunk, "content", None):
                    yield {"type": "token", "data": {"content": chunk.content}}