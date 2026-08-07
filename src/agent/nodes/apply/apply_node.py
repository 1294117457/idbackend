"""申请节点 - HITL 完整实现

流程：
1. 解析用户输入的条件（LLM 提取）
2. 模板匹配（RAG + 结构化提取）
3. 分支：
   - 0 匹配 → 直接返回"未匹配"
   - 1 匹配 → 进入确认流程
   - 多匹配 → interrupt(select_template) 让用户选
4. RAG 检索适用政策
5. interrupt(confirm) 让用户确认
6. 提交申请（写入 Application 表）
7. 返回结果
"""
import logging
from typing import Dict, Any, List, Optional

from langgraph.types import interrupt

from src.agent.state import AgentState
from src.agent.nodes.apply.apply_prompt import APPLY_PROMPT
from src.infra.ai.model import get_chat_model

logger = logging.getLogger(__name__)


async def apply_node(state: AgentState) -> Dict[str, Any]:
    """资助申请节点"""
    messages = state.get("messages", [])
    user_id = state.get("user_id")
    session_id = state.get("session_id")

    if not messages:
        return _fallback("未收到有效输入")

    user_content = messages[-1].get("content", "")
    if not user_content:
        return _fallback("未收到有效输入")

    logger.info(f"[apply_node] user_id={user_id}, input={user_content[:50]}...")

    # ── Step 1: 解析用户条件 ──────────────────────────────────────────
    conditions = await _parse_conditions(user_content)
    if not conditions:
        return _fallback(
            "未能理解您的申请意向，请描述您想申请的资助类型或具体需求。"
        )

    # ── Step 2: 模板匹配 ─────────────────────────────────────────────
    matched_templates = await _match_templates(conditions)
    if not matched_templates:
        return _fallback(
            f"根据您提供的信息（{conditions.get('summary', '')}），"
            f"暂未匹配到适合您的资助项目。您可以换个条件试试，或联系管理员。"
        )

    # ── Step 3: 决策分支 ─────────────────────────────────────────────
    # 单模板：直接用
    if len(matched_templates) == 1:
        selected_template = matched_templates[0]
    else:
        # 多模板：interrupt 让用户选择
        select_data = {
            "type": "select_template",
            "templates": [
                {
                    "id": t["id"],
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "conditions": t.get("conditions", []),
                }
                for t in matched_templates
            ],
            "prompt": f"匹配到 {len(matched_templates)} 个资助项目，请选择一个：",
        }
        # 从 resume 中提取 template_id（前端发送 {"action": "select", "template_id": 5}）
        raw_choice = interrupt(select_data)
        choice_id: str
        if isinstance(raw_choice, dict):
            choice_id = str(raw_choice.get("template_id") or raw_choice.get("id", ""))
        else:
            choice_id = str(raw_choice)
        selected_template = next(
            (t for t in matched_templates if str(t["id"]) == choice_id),
            matched_templates[0],
        )
        logger.info(f"[apply_node] 用户选择模板: id={choice_id}, name={selected_template['name']}")

    logger.info(f"[apply_node] 选中模板: {selected_template['name']}")

    # ── Step 4: RAG 检索适用政策 ────────────────────────────────────
    rag_context = await _search_policy(selected_template)

    # ── Step 5: 确认中断 ─────────────────────────────────────────────
    confirm_data = {
        "type": "confirm_apply",
        "template_id": selected_template["id"],
        "template_name": selected_template["name"],
        "template_description": selected_template.get("description", ""),
        "fields": selected_template.get("conditions", []),
        "rag_context": rag_context,
        "prompt": "请确认以下申请信息",
    }
    user_confirm = interrupt(confirm_data)

    # 解析用户决策
    action = (
        user_confirm.get("action", "")
        if isinstance(user_confirm, dict)
        else str(user_confirm)
    )

    if action == "cancel":
        return {
            "generated_text": (
                "已取消申请。如有需要可随时重新咨询，祝您学业顺利！"
            ),
            "sources": [],
            "rag_context": rag_context,
        }

    if action == "supplement":
        additional_info = user_confirm.get("info", "")
        new_content = user_content + "\n补充信息：" + additional_info
        new_state = {**state, "messages": messages[:-1] + [{"content": new_content}]}
        return await apply_node(new_state)

    # action == "confirm" 或其他有效值：提交申请
    # selected_template 已在 Step 3 或 Step 5 前置确定
    if action not in ("confirm", ""):
        logger.warning(f"[apply_node] 未识别的 action={action}，视为确认提交")

    # ── Step 6: 提交申请 ─────────────────────────────────────────────
    application = await _submit_application(user_id, selected_template)

    # ── Step 7: 返回结果 ─────────────────────────────────────────────
    return {
        "generated_text": (
            f"申请已成功提交！\n\n"
            f"资助项目：{selected_template['name']}\n"
            f"申请单号：{application['application_id']}\n\n"
            f"申请状态：待审核\n"
            f"{'相关政策已显示在上方。' if rag_context else ''}"
        ),
        "sources": [str(selected_template["id"])],
        "rag_context": rag_context,
    }


def _fallback(text: str) -> Dict[str, Any]:
    return {"generated_text": text, "sources": [], "rag_context": ""}


async def _parse_conditions(user_content: str) -> Optional[Dict[str, Any]]:
    """从用户输入中解析申请条件"""
    from pydantic import BaseModel, Field

    class ConditionOutput(BaseModel):
        summary: str = Field(description="条件摘要")
        amount: Optional[str] = Field(default=None, description="期望资助金额")
        duration: Optional[str] = Field(default=None, description="资助时长")
        category: Optional[str] = Field(default=None, description="资助类别")
        other: Optional[str] = Field(default=None, description="其他条件")

    PROMPT = f"""{APPLY_PROMPT}

用户申请内容：
{user_content}

请提取以下信息（如果用户未提供则填 null）：
- summary: 申请意图的简短摘要（必填）
- amount: 期望资助金额（如有）
- duration: 资助时长（如有）
- category: 资助类别（如：助学金、奖学金、补贴、贷款、其他）
- other: 其他补充条件（如有）
"""
    try:
        llm = get_chat_model()
        response = await llm.with_structured_output(ConditionOutput).ainvoke(PROMPT)
        return {
            "summary": response.summary,
            "amount": response.amount,
            "duration": response.duration,
            "category": response.category,
            "other": response.other,
        }
    except Exception as e:
        logger.warning(f"[_parse_conditions] LLM 解析失败: {e}")
        return {"summary": user_content[:100]}


async def _match_templates(conditions: Dict[str, Any]) -> List[Dict[str, Any]]:
    """根据条件匹配资助模板"""
    from src.services.template_service import TemplateService
    from src.infra.database import get_db_context

    matched = []

    try:
        async with get_db_context() as db:
            templates = await TemplateService.list_all(db, is_active=True)
            for t in templates:
                score = _calc_match_score(t, conditions)
                if score >= 0.3:
                    matched.append({
                        "id": t.id,
                        "name": t.name,
                        "description": t.description,
                        "conditions": _extract_template_conditions(t),
                        "match_score": score,
                    })

        # 按匹配分排序
        matched.sort(key=lambda x: x.get("match_score", 0), reverse=True)
        return matched[:5]  # 最多返回 5 个
    except Exception as e:
        logger.error(f"[_match_templates] 模板匹配失败: {e}")
        return []


def _calc_match_score(template, conditions: Dict[str, Any]) -> float:
    """计算模板匹配分（简单规则 + 关键词匹配）"""
    score = 0.0
    summary = conditions.get("summary", "")
    category = conditions.get("category", "")
    amount = conditions.get("amount", "")
    duration = conditions.get("duration", "")

    t_name = template.name or ""
    t_desc = template.description or ""

    keywords = [t_name, t_desc]
    if any(kw and (kw in summary or summary in kw) for kw in keywords):
        score += 0.5
    if category and category in t_name:
        score += 0.3
    if amount and amount in t_desc:
        score += 0.1
    if duration and duration in t_desc:
        score += 0.1

    return score


def _extract_template_conditions(template) -> List[Dict[str, str]]:
    """从 Template ORM 对象提取用于前端展示的条件"""
    conditions = []
    for rule in template.rules:
        if rule.is_active:
            conditions.append({
                "name": rule.name,
                "description": rule.description or "",
                "type": rule.type,
            })
    return conditions


async def _search_policy(template: Dict[str, Any]) -> str:
    """RAG 检索适用政策"""
    from src.services.embedding_service import get_embedding_service
    from src.infra.database import get_db_context

    query = f"{template.get('name', '')} {template.get('description', '')}"
    try:
        async with get_db_context() as db:
            svc = get_embedding_service()
            result = await svc.rrf_search(
                db, query=query, category="policy", top_k=3
            )

        if not result.hits:
            return ""

        parts = []
        for i, hit in enumerate(result.hits, 1):
            title = hit.get("title", "未知来源")
            content = hit.get("content", "")
            parts.append(f"[{i}] {title}\n{content}")
        return "\n\n".join(parts)
    except Exception as e:
        logger.warning(f"[_search_policy] RAG 检索失败: {e}")
        return ""


async def _submit_application(
    user_id: int,
    template: Dict[str, Any],
) -> Dict[str, Any]:
    """写入 Application 表"""
    from src.models import Application, ApplicationStatus
    from src.repositories.application_repo import ApplicationRepository
    from src.infra.database import get_db_context

    async with get_db_context() as db:
        application = Application(
            user_id=user_id,
            template_id=template["id"],
            template_name=template["name"],
            status=ApplicationStatus.APPLYING.value,
        )
        result = await ApplicationRepository.insert(db, application)
        return {"application_id": result.id, "status": result.status}
