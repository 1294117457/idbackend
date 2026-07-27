"""AI Chat 服务层

职责：
- 会话管理（创建、删除）
- 消息管理（创建、查询）
- 上下文组装（供 LangGraph 使用）
"""
import logging
from typing import Optional, List, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.ai_chat import (
    AgentSession,
    MessageRole,
    MessageType,
)
from src.repositories.ai_chat_repo import AIChatRepository
from src.app.schemas.ai_chat import (
    SessionVO,
    MessageVO,
    SessionListVO,
    MessageListVO,
    SessionListRequest,
)
from src.app.schemas.page import Page

logger = logging.getLogger(__name__)


class AIChatService:
    """AI Chat 服务层"""

    # ─────────────────────────────────────────────────────────────────────────
    # Session 管理
    # ─────────────────────────────────────────────────────────────────────────

    async def get_or_create_session(
        self,
        db: AsyncSession,
        user_id: int,
        session_id: Optional[int] = None,
        first_message: Optional[str] = None,
    ) -> AgentSession:
        """获取或创建会话

        - session_id 有值：直接返回
        - session_id 为空/0：创建新会话
        """
        if session_id:
            session = await AIChatRepository.get_session_by_id(db, session_id)
            if session:
                return session

        # 创建新会话，标题取自第一条消息前 20 字
        title = "新会话"
        if first_message:
            title = first_message[:20] if len(first_message) > 20 else first_message

        session = await AIChatRepository.create_session(db, user_id, title=title)
        await AIChatRepository.commit(db)
        return session

    async def list_sessions(
        self,
        db: AsyncSession,
        user_id: int,
        request: Optional[SessionListRequest] = None,
    ) -> SessionListVO:
        """查询用户会话列表"""
        if request is None:
            request = SessionListRequest()

        sessions, total = await AIChatRepository.list_sessions_by_user(
            db,
            user_id,
            page_num=request.page_num,
            page_size=request.page_size,
        )

        items = [SessionVO.from_orm(s) for s in sessions]
        return Page.from_list_to_page(items, total, request.page_num, request.page_size)

    async def delete_session(
        self,
        db: AsyncSession,
        session_id: int,
    ) -> bool:
        """删除会话"""
        result = await AIChatRepository.delete_session(db, session_id)
        if result:
            await AIChatRepository.commit(db)
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Message 管理
    # ─────────────────────────────────────────────────────────────────────────

    async def list_messages(
        self,
        db: AsyncSession,
        session_id: int,
        page_num: int = 1,
        page_size: int = 50,
    ) -> MessageListVO:
        """查询会话消息列表"""
        messages, total = await AIChatRepository.list_messages_by_session(
            db,
            session_id,
            page_num=page_num,
            page_size=page_size,
        )

        items = [MessageVO.from_orm(m) for m in messages]
        return Page.from_list_to_page(items, total, page_num, page_size)

    async def get_recent_messages(
        self,
        db: AsyncSession,
        session_id: int,
        limit: int = 10,
    ) -> List[MessageVO]:
        """获取最近 N 条消息（用于上下文组装）"""
        messages = await AIChatRepository.list_recent_messages(db, session_id, limit)
        return [MessageVO.from_orm(m) for m in reversed(messages)]

    # ─────────────────────────────────────────────────────────────────────────
    # 对话核心
    # ─────────────────────────────────────────────────────────────────────────

    async def build_llm_messages(
        self,
        db: AsyncSession,
        session_id: int,
        user_input: str,
        system_prompt: Optional[str] = None,
        context_window: int = 20,
    ) -> List[dict]:
        """构建 LLM 消息列表（含历史摘要 + 最近消息）

        组装顺序（重要）:
        1. system prompt
        2. 历史摘要 (1 个) → 长期记忆
        3. 近期摘要 (最多 N 个, 按 end_seq 升序) → 中期记忆
        4. 最近 context_window 条原始消息 (按 seq 升序) → 短期记忆
        5. 当前用户输入
        """
        from src.infra.config import get_settings

        cfg = get_settings()
        messages: List[dict] = []

        # 1. system prompt
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # 2. 历史摘要（最多 1 个）
        archived = await AIChatRepository.list_summaries(
            db, session_id, is_archived=True, order_by="end_seq DESC", limit=1
        )
        if archived:
            s = archived[0]
            messages.append({
                "role": "system",
                "content": f"[历史背景 seq={s.start_seq}-{s.end_seq}] {s.summary}",
            })

        # 3. 近期摘要（按 end_seq ASC）
        recent_summaries = await AIChatRepository.list_summaries(
            db, session_id,
            is_archived=False,
            order_by="end_seq ASC",
            limit=cfg.SUMMARY_RECENT_MAX_COUNT,
        )
        for s in recent_summaries:
            messages.append({
                "role": "system",
                "content": f"[近期摘要 seq={s.start_seq}-{s.end_seq}] {s.summary}",
            })

        # 4. 最近 N 条原始消息
        recent_msgs = await AIChatRepository.list_recent_messages(
            db, session_id, limit=context_window
        )
        recent_msgs.reverse()  # 倒序 → 升序
        for msg in recent_msgs:
            role = "user" if msg.role == MessageRole.USER.value else "assistant"
            messages.append({"role": role, "content": msg.content})

        # 5. 当前用户输入
        messages.append({"role": "user", "content": user_input})
        return messages

    async def stream_chat(
        self,
        db: AsyncSession,
        user_id: int,
        user_input: str,
        session_id: Optional[int] = None,
    ) -> AsyncIterator[dict]:
        """流式对话

        1. 获取或创建会话
        2. 保存用户消息
        3. 触发压缩（如需要, 同步阻塞, <3s 感知不明显）
        4. 构建 LLM 上下文（含摘要）
        5. 流式调用 LLM
        6. 返回 SSE 事件

        事件类型：
        - session: 新建会话信息（仅新建时）
        - content: LLM 回复片段
        - context_compressed: 触发了压缩
        - done: 完成
        - error: 错误
        """
        from src.infra.ai.model import get_chat_model
        from src.services.compress_service import get_compress_service

        # 获取或创建会话
        session = await self.get_or_create_session(
            db, user_id, session_id, first_message=user_input
        )
        current_session_id = session.id

        # 检查是否新建了会话
        is_new_session = session_id is None or session_id == 0

        # 保存用户消息
        user_msg = await AIChatRepository.create_message(
            db,
            session_id=current_session_id,
            role=MessageRole.USER,
            content=user_input,
            msg_type=MessageType.TEXT,
        )
        await db.flush()

        # 新建会话时返回会话信息
        if is_new_session:
            yield {
                "event": "session",
                "data": {
                    "id": session.id,
                    "title": session.title,
                }
            }

        # 触发压缩（如需要）
        compress_service = get_compress_service()
        compressed_id = await compress_service.maybe_compress(
            db, current_session_id
        )
        if compressed_id is not None:
            await db.commit()
            yield {
                "event": "context_compressed",
                "data": {
                    "message": "已压缩历史上下文",
                    "summaryId": compressed_id,
                }
            }

        # 构建消息列表（含历史/近期摘要）
        system_prompt = (
            "你是一个智能助手，帮助用户解答关于学生资助申请相关的问题。"
            "请用简洁、友好的语言回答。"
        )
        messages = await self.build_llm_messages(
            db, current_session_id, user_input, system_prompt
        )

        # 流式调用 LLM
        from src.infra.config import get_llm_config
        llm = get_chat_model()
        cfg = get_llm_config()
        try:
            full_content = ""
            async for chunk in llm.astream(messages):
                if chunk.content:
                    full_content += chunk.content
                    yield {
                        "event": "content",
                        "data": {
                            "content": chunk.content,
                            "messageId": user_msg.id,
                        }
                    }

            await db.commit()

            # 保存 LLM 回复
            assistant_msg = await AIChatRepository.create_message(
                db,
                session_id=current_session_id,
                role=MessageRole.ASSISTANT,
                content=full_content,
                msg_type=MessageType.TEXT,
            )
            await db.commit()

            yield {
                "event": "done",
                "data": {
                    "messageId": assistant_msg.id,
                    "content": full_content,
                }
            }

        except Exception as e:
            import traceback
            logger.error(f"LLM 调用失败: {e}")
            logger.error(f"LLM 配置: base_url={cfg.get('base_url')}, model={cfg.get('chat_model')}")
            logger.error(f"LLM 错误详情: {traceback.format_exc()}")
            yield {
                "event": "error",
                "data": {"message": str(e)}
            }


# 全局单例
_ai_chat_service: Optional[AIChatService] = None


def get_ai_chat_service() -> AIChatService:
    """获取 AIChatService 单例"""
    global _ai_chat_service
    if _ai_chat_service is None:
        _ai_chat_service = AIChatService()
    return _ai_chat_service


__all__ = ["AIChatService", "get_ai_chat_service"]
