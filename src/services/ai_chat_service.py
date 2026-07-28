"""AI Chat 服务层

职责:
- 会话管理（创建、删除、查询）
- 消息管理（创建、查询）
- 对话入口（stream_chat）
- LangGraph 工具方法（build_context / maybe_compress）
- 上下文压缩（私有 LLM 摘要方法）
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.ai_chat import (
    AgentMessage,
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
from src.infra.config import get_settings

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────
# 压缩相关 Prompt 模板（硬约束字数）
# ────────────────────────────────────────────────────────────────────────

SUMMARY_PROMPT = """请将以下对话历史压缩为简洁摘要。

要求：
- 总字数不超过 {max_chars} 字
- 必须保留：用户意图、已获取的事实、已做出的决定、待办事项
- 舍弃：寒暄、重复确认、礼貌用语

对话历史：
{messages_text}

摘要："""

MERGE_PROMPT = """将以下两段历史摘要合并为一段（{target_chars} 字以内），
保留所有关键信息:
- 用户意图、事实、决定、待办
- 去除重复描述、舍弃次要细节

摘要 A (较早):
{old_text}

摘要 B (较新):
{new_text}

合并后的摘要:"""

RESUMMARIZE_PROMPT = """以下历史摘要过长，请重新压缩到 {target_chars} 字以内。
保留所有关键信息，舍弃次要细节。

当前摘要:
{text}

压缩后的摘要:"""


def _format_messages(messages: List[AgentMessage]) -> str:
    return "\n".join(f"[{m.role.value}] {m.content}" for m in messages)


class AIChatService:
    """AI Chat 服务层

    入口（业务层）:
      - stream_chat(db, user_id, user_input, session_id)  # SSE 流式对话

    LangGraph 工具方法:
      - build_context(...)              # 灵活组装 context
      - maybe_compress(db, session_id)  # 触发压缩判断

    基础 CRUD:
      - get_or_create_session / list_sessions / delete_session
      - list_messages / get_recent_messages
    """

    # ────────────────────────────────────────────────────────────────────────
    # Session 管理
    # ────────────────────────────────────────────────────────────────────────

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
            return result
        return result

    # ────────────────────────────────────────────────────────────────────────
    # Message 管理
    # ────────────────────────────────────────────────────────────────────────

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

    # ────────────────────────────────────────────────────────────────────────
    # LangGraph 工具方法：组装 context
    # ────────────────────────────────────────────────────────────────────────

    async def build_context(
        self,
        db: AsyncSession,
        session_id: int,
        user_input: str,
        system_prompt: Optional[str] = None,
        *,
        include_archived: bool = True,
        recent_summaries_limit: Optional[int] = None,
        recent_messages_limit: int = 20,
    ) -> List[dict]:

        cfg = get_settings()
        messages: List[dict] = []

        # 1. system prompt
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # 2. 历史摘要（最多 1 个）
        if include_archived:
            archived = await AIChatRepository.list_summaries(
                db, session_id, is_archived=True, order_by="end_seq DESC", limit=1
            )
            for s in archived:
                messages.append({
                    "role": "system",
                    "content": f"[历史背景 seq={s.start_seq}-{s.end_seq}] {s.summary}",
                })

        # 3. 近期摘要
        if recent_summaries_limit is None:
            recent_limit = cfg.SUMMARY_RECENT_MAX_COUNT
        else:
            recent_limit = recent_summaries_limit

        if recent_limit > 0:
            recent_summaries = await AIChatRepository.list_summaries(
                db, session_id,
                is_archived=False,
                order_by="end_seq ASC",
                limit=recent_limit,
            )
            for s in recent_summaries:
                messages.append({
                    "role": "system",
                    "content": f"[近期摘要 seq={s.start_seq}-{s.end_seq}] {s.summary}",
                })

        # 4. 近期原始消息
        if recent_messages_limit > 0:
            recent_msgs = await AIChatRepository.list_recent_messages(
                db, session_id, limit=recent_messages_limit
            )
            recent_msgs.reverse()  # 倒序 → 升序
            for msg in recent_msgs:
                role = "user" if msg.role == MessageRole.USER.value else "assistant"
                messages.append({"role": role, "content": msg.content})

        # 5. 当前用户输入
        messages.append({"role": "user", "content": user_input})
        return messages

    # ────────────────────────────────────────────────────────────────────────
    # LangGraph 工具方法：压缩触发
    # ────────────────────────────────────────────────────────────────────────

    async def should_compress(self, db: AsyncSession, session_id: int) -> bool:
        """判断是否应该触发压缩

        - 首次: 总消息数 >= compress_interval 触发
        - 非首次: MAX(seq) - last_summary_end_seq >= compress_interval 触发
        """
        cfg = get_settings()
        snapshot = await AIChatRepository.get_snapshot(db, session_id)
        latest_seq = await AIChatRepository.get_latest_seq(db, session_id)
        if latest_seq is None:
            return False

        if snapshot is None:
            return latest_seq >= cfg.SUMMARY_COMPRESS_INTERVAL

        diff = latest_seq - snapshot.last_summary_end_seq
        return diff >= cfg.SUMMARY_COMPRESS_INTERVAL

    async def maybe_compress(self, db: AsyncSession, session_id: int) -> Optional[int]:
        """判断并触发压缩

        Returns:
            - 新生成的近期摘要 ID
            - None 不需要压缩
        """
        if not await self.should_compress(db, session_id):
            return None
        return await self.do_compress(db, session_id)

    async def do_compress(self, db: AsyncSession, session_id: int) -> Optional[int]:
        """执行压缩 (强制)

        流程:
        1. 计算压缩范围 (start_seq ~ end_seq)
        2. 拉取消息, 调用 LLM 生成摘要 (近期)
        3. 检查近期数量, 超 RECENT_MAX_COUNT 触发合并
        4. upsert snapshot
        """
        cfg = get_settings()
        snapshot = await AIChatRepository.get_snapshot(db, session_id)
        latest_seq = await AIChatRepository.get_latest_seq(db, session_id)
        if latest_seq is None:
            return None

        # 1. 计算范围
        if snapshot:
            start_seq = snapshot.last_summary_end_seq + 1
        else:
            start_seq = 1
        end_seq = latest_seq

        # 不够触发区间, 跳过
        if end_seq - start_seq + 1 < cfg.SUMMARY_COMPRESS_INTERVAL:
            return None

        # 2. 拉取消息 + LLM 摘要
        messages = await AIChatRepository.get_messages_range(
            db, session_id, start_seq, end_seq
        )
        if not messages:
            return None
        summary_text = await self._generate_summary(messages)

        # 3. 写入近期摘要
        new_summary = await AIChatRepository.create_summary(
            db,
            session_id=session_id,
            summary=summary_text,
            start_seq=start_seq,
            end_seq=end_seq,
            is_archived=False,
        )
        await db.flush()

        # 4. 近期超出 -> 合并最旧到历史
        recent = await AIChatRepository.list_summaries(
            db, session_id, is_archived=False, order_by="end_seq ASC"
        )
        merged = False
        if len(recent) > cfg.SUMMARY_RECENT_MAX_COUNT:
            await self._merge_oldest_to_archive(db, session_id)
            merged = True

        # 5. 重新读近期用于 snapshot 计数
        recent = await AIChatRepository.list_summaries(
            db, session_id, is_archived=False, order_by="end_seq ASC"
        )
        archived_count = len(
            await AIChatRepository.list_summaries(
                db, session_id, is_archived=True
            )
        )

        # 6. upsert snapshot
        await AIChatRepository.upsert_snapshot(
            db,
            session_id=session_id,
            last_summary_end_seq=end_seq,
            recent_summary_count=len(recent),
            last_summary_at=datetime.now(timezone.utc),
            total_summary_count=len(recent) + archived_count,
        )
        await db.flush()

        if merged:
            logger.info(
                f"[compress] session={session_id} merged oldest summary "
                f"(recent now={len(recent)})"
            )
        return new_summary.id

    # ────────────────────────────────────────────────────────────────────────
    # 私有方法：摘要合并 / 再压缩 / LLM 调用
    # ────────────────────────────────────────────────────────────────────────

    async def _merge_oldest_to_archive(
        self, db: AsyncSession, session_id: int
    ) -> None:
        """把最旧的近期摘要合并到历史摘要

        1. 取最旧近期 (end_seq ASC, limit 1)
        2. 找现有历史
           - 有: LLM 合并 -> 扩展 seq -> 删除被合并的近期
           - 无: 直接把最旧近期升级为历史
        3. 防御性: 历史超阈值触发再压缩
        """
        cfg = get_settings()
        recent = await AIChatRepository.list_summaries(
            db, session_id, is_archived=False, order_by="end_seq ASC", limit=1
        )
        if not recent:
            return
        oldest = recent[0]

        archived = await AIChatRepository.list_summaries(
            db, session_id, is_archived=True, limit=1
        )

        if archived:
            archive = archived[0]
            merged_text = await self._merge_summary_texts(
                old_text=archive.summary,
                new_text=oldest.summary,
                target_chars=cfg.SUMMARY_MERGE_TARGET_CHARS,
            )
            await AIChatRepository.update_summary(
                db,
                archive.id,
                summary_text=merged_text,
                start_seq=min(archive.start_seq, oldest.start_seq),
                end_seq=oldest.end_seq,
            )
            await AIChatRepository.delete_summary(db, oldest.id)
        else:
            await AIChatRepository.update_summary(
                db, oldest.id, is_archived=True
            )

        # 防御性: 历史摘要超过阈值, 触发再压缩
        archived_after = await AIChatRepository.list_summaries(
            db, session_id, is_archived=True, limit=1
        )
        if archived_after:
            ar = archived_after[0]
            if len(ar.summary) > cfg.SUMMARY_ARCHIVED_MAX_CHARS:
                new_text = await self._resummarize_text(
                    text=ar.summary,
                    target_chars=cfg.SUMMARY_ARCHIVED_MAX_CHARS,
                )
                await AIChatRepository.update_summary(
                    db, ar.id, summary_text=new_text
                )

    async def _generate_summary(self, messages: List[AgentMessage]) -> str:
        """生成近期摘要 (字数硬约束 = SUMMARY_RECENT_MAX_CHARS)"""
        from src.infra.ai.model import get_chat_model

        cfg = get_settings()
        text = _format_messages(messages)
        prompt = SUMMARY_PROMPT.format(
            max_chars=cfg.SUMMARY_RECENT_MAX_CHARS,
            messages_text=text,
        )
        llm = get_chat_model()
        resp = await llm.ainvoke(prompt)
        return resp.content

    async def _merge_summary_texts(
        self, old_text: str, new_text: str, target_chars: int
    ) -> str:
        """合并两段摘要 (调用 LLM)"""
        from src.infra.ai.model import get_chat_model

        prompt = MERGE_PROMPT.format(
            target_chars=target_chars,
            old_text=old_text,
            new_text=new_text,
        )
        llm = get_chat_model()
        resp = await llm.ainvoke(prompt)
        return resp.content

    async def _resummarize_text(self, text: str, target_chars: int) -> str:
        """历史超阈值时, 重新压缩"""
        from src.infra.ai.model import get_chat_model

        prompt = RESUMMARIZE_PROMPT.format(
            target_chars=target_chars, text=text
        )
        llm = get_chat_model()
        resp = await llm.ainvoke(prompt)
        return resp.content

    # ────────────────────────────────────────────────────────────────────────
    # 对话入口（业务层）
    # ────────────────────────────────────────────────────────────────────────

    async def stream_chat(
        self,
        db: AsyncSession,
        user_id: int,
        user_input: str,
        session_id: Optional[int] = None,
    ) -> AsyncIterator[dict]:
        """流式对话（Step 6 改造后：拆短事务 + LangGraph）

        事务边界：
        - 事务 1：准备（创建 session + user_msg + 压缩 + build_context）
        - [Graph 调用（不持锁 db 连接）]
        - 事务 2：完成（assistant_msg）

        LangGraph 流程：
        - classify（意图识别）
        - router（路由判断）
        - chat（闲聊）

        收益：
        - LLM 期间不持锁连接 → 连接池不被阻塞
        - 客户端断开时事务状态清晰
        - 支持意图路由、节点扩展
        """
        from src.infra.database import get_db_context

        logger.info(f"[stream_chat] user_id={user_id}, session_id={session_id}, user_input={user_input!r}")

        # ===== 事务 1：准备阶段 =====
        async with get_db_context() as db:
            # 获取或创建会话
            session = await self.get_or_create_session(
                db, user_id, session_id, first_message=user_input
            )
            current_session_id = session.id
            logger.info(f"[stream_chat] 会话: current_session_id={current_session_id}")

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
            logger.info(f"[stream_chat] 用户消息已保存: user_msg.id={user_msg.id}")

            # 触发压缩（如需要）
            compressed_id = await self.maybe_compress(db, current_session_id)

            # 构建消息列表（含历史/近期摘要）—— 在事务 1 里查完
            system_prompt = (
                "你是一个智能助手，帮助用户解答关于学生资助申请相关的问题。"
                "请用简洁、友好的语言回答。"
            )
            messages = await self.build_context(
                db,
                current_session_id,
                user_input,
                system_prompt,
                include_archived=True,
                recent_summaries_limit=None,  # 使用默认 SUMMARY_RECENT_MAX_COUNT
                recent_messages_limit=20,
            )
            logger.info(f"[stream_chat] 构建上下文完成: {len(messages)} 条消息")

        # ↑ 事务 1 commit：user_msg + compressed_id 落盘

        # ===== 准备完成事件 =====
        if is_new_session:
            logger.info(f"[stream_chat] 发送 session 事件: id={session.id}, title={session.title}")
            yield {
                "event": "session",
                "data": {
                    "id": session.id,
                    "title": session.title,
                }
            }
        if compressed_id is not None:
            logger.info(f"[stream_chat] 发送 context_compressed 事件")
            yield {
                "event": "context_compressed",
                "data": {
                    "message": "已压缩历史上下文",
                    "summaryId": compressed_id,
                }
            }

        # ===== LLM 调用（无 db 持锁）=====
        # 方式：调用 LangGraph
        full_content = ""

        # 导入 Graph
        from src.agent.graph.builder import get_compiled_graph

        graph = get_compiled_graph()
        state = {
            "messages": messages,
            "user_id": user_id,
            "session_id": str(current_session_id),
        }
        logger.info(f"[stream_chat] 开始调用 LangGraph, state={state}")

        try:
            # 使用 astream 获取节点输出
            async for node_output in graph.astream(
                state,
                config={"configurable": {"thread_id": str(current_session_id)}}
            ):
                logger.info(f"[stream_chat] 收到节点输出: {node_output}")
                # node_output 格式: {"classify": {"intent": "chat"}} 或 {"chat": {"generated_text": "..."}}
                for node_name, node_result in node_output.items():
                    if isinstance(node_result, dict) and "generated_text" in node_result:
                        content = node_result["generated_text"]
                        full_content += content
                        yield {
                            "event": "content",
                            "data": {
                                "content": content,
                                "messageId": user_msg.id,
                            }
                        }
        except Exception as e:
            # ↑ LLM 调用失败 → 异常处理
            # ↑ user_msg 已落盘（事务 1 commit），assistant_msg 不写
            # ↑ 客户端看到部分 content 但 assistant_msg 不在历史里（流式响应固有缺陷）
            import traceback
            logger.error(f"Graph 调用失败: {e}")
            logger.error(f"错误详情: {traceback.format_exc()}")
            yield {
                "event": "error",
                "data": {"message": str(e)}
            }
            return

        # ===== 事务 2：完成阶段 =====
        async with get_db_context() as db:
            # 保存 LLM 回复
            assistant_msg = await AIChatRepository.create_message(
                db,
                session_id=current_session_id,
                role=MessageRole.ASSISTANT,
                content=full_content,
                msg_type=MessageType.TEXT,
            )
            logger.info(f"[stream_chat] assistant_msg 已保存: id={assistant_msg.id}")

        # ↑ 事务 2 commit：assistant_msg 落盘

        yield {
            "event": "done",
            "data": {
                "messageId": assistant_msg.id,
                "content": full_content,
            }
        }
        logger.info(f"[stream_chat] 完成: full_content长度={len(full_content)}")


# 全局单例
_ai_chat_service: Optional[AIChatService] = None


def get_ai_chat_service() -> AIChatService:
    """获取 AIChatService 单例"""
    global _ai_chat_service
    if _ai_chat_service is None:
        _ai_chat_service = AIChatService()
    return _ai_chat_service


__all__ = ["AIChatService", "get_ai_chat_service"]
