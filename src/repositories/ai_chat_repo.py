"""AI Chat 数据访问层

职责：
- 只做"读 / 写 ORM"，没有业务规则
- 所有 SQLAlchemy 调用集中在此
"""
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import select, delete, func, and_, or_, desc, asc
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.ai_chat import (
    AgentSession,
    AgentMessage,
    AgentSessionSummary,
    AgentSessionSnapshot,
    SessionStatus,
    MessageRole,
)


class AIChatRepository:
    """AI Chat 数据访问层"""

    # ─────────────────────────────────────────────────────────────────────────
    # Session 操作
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    async def get_session_by_id(
        db: AsyncSession,
        session_id: int,
    ) -> Optional[AgentSession]:
        """按主键查会话"""
        stmt = select(AgentSession).where(AgentSession.id == session_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_session_with_messages(
        db: AsyncSession,
        session_id: int,
    ) -> Optional[AgentSession]:
        """按主键查会话（含消息）"""
        stmt = (
            select(AgentSession)
            .options(selectinload(AgentSession.messages))
            .where(AgentSession.id == session_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_sessions_by_user(
        db: AsyncSession,
        user_id: int,
        *,
        status: Optional[SessionStatus] = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[AgentSession], int]:
        """按用户查询会话列表（分页）"""
        conds = [AgentSession.user_id == user_id]
        if status:
            conds.append(AgentSession.status == status)

        # 统计
        count_stmt = select(func.count(AgentSession.id)).where(and_(*conds))
        count_result = await db.execute(count_stmt)
        total = int(count_result.scalar_one() or 0)

        # 分页
        offset = (page_num - 1) * page_size
        stmt = (
            select(AgentSession)
            .where(and_(*conds))
            .order_by(AgentSession.updated_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await db.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    @staticmethod
    async def create_session(
        db: AsyncSession,
        user_id: int,
        title: str = "新会话",
    ) -> AgentSession:
        """创建新会话"""
        session = AgentSession(user_id=user_id, title=title)
        db.add(session)
        await db.flush()
        return session

    @staticmethod
    async def update_session_title(
        db: AsyncSession,
        session_id: int,
        title: str,
    ) -> Optional[AgentSession]:
        """更新会话标题"""
        session = await db.get(AgentSession, session_id)
        if session:
            session.title = title
            await db.flush()
        return session

    @staticmethod
    async def archive_session(
        db: AsyncSession,
        session_id: int,
    ) -> Optional[AgentSession]:
        """归档会话"""
        session = await db.get(AgentSession, session_id)
        if session:
            session.status = SessionStatus.ARCHIVED
            await db.flush()
        return session

    @staticmethod
    async def delete_session(
        db: AsyncSession,
        session_id: int,
    ) -> bool:
        """删除会话"""
        session = await db.get(AgentSession, session_id)
        if session:
            await db.delete(session)
            await db.flush()
            return True
        return False

    # ─────────────────────────────────────────────────────────────────────────
    # Message 操作
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    async def get_message_by_id(
        db: AsyncSession,
        message_id: int,
    ) -> Optional[AgentMessage]:
        """按主键查消息"""
        return await db.get(AgentMessage, message_id)

    @staticmethod
    async def list_messages_by_session(
        db: AsyncSession,
        session_id: int,
        *,
        page_num: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[AgentMessage], int]:
        """按会话查询消息列表（分页，按 seq 升序）"""
        conds = [AgentMessage.session_id == session_id]

        # 统计
        count_stmt = select(func.count(AgentMessage.id)).where(and_(*conds))
        count_result = await db.execute(count_stmt)
        total = int(count_result.scalar_one() or 0)

        # 分页
        offset = (page_num - 1) * page_size
        stmt = (
            select(AgentMessage)
            .where(and_(*conds))
            .order_by(AgentMessage.seq.asc())
            .offset(offset)
            .limit(page_size)
        )
        result = await db.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    @staticmethod
    async def list_recent_messages(
        db: AsyncSession,
        session_id: int,
        limit: int = 10,
    ) -> List[AgentMessage]:
        """查询最近 N 条消息（用于上下文）"""
        stmt = (
            select(AgentMessage)
            .where(AgentMessage.session_id == session_id)
            .order_by(AgentMessage.seq.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_next_seq(
        db: AsyncSession,
        session_id: int,
    ) -> int:
        """获取下一个 seq 序号"""
        stmt = (
            select(func.max(AgentMessage.seq))
            .where(AgentMessage.session_id == session_id)
        )
        result = await db.execute(stmt)
        max_seq = result.scalar_one_or_none()
        return (max_seq or 0) + 1

    @staticmethod
    async def create_message(
        db: AsyncSession,
        session_id: int,
        role: MessageRole,
        content: str,
        msg_type: str = "text",
        sources: Optional[List[dict]] = None,
        tool_calls: Optional[List[dict]] = None,
    ) -> AgentMessage:
        """创建消息"""
        seq = await AIChatRepository.get_next_seq(db, session_id)
        message = AgentMessage(
            session_id=session_id,
            role=role,
            content=content,
            msg_type=msg_type,
            sources=sources,
            tool_calls=tool_calls,
            seq=seq,
        )
        db.add(message)
        await db.flush()

        # 更新会话的 updated_at
        session = await db.get(AgentSession, session_id)
        if session:
            session.updated_at = datetime.now()

        return message

    @staticmethod
    async def update_message_content(
        db: AsyncSession,
        message_id: int,
        content: str,
    ) -> Optional[AgentMessage]:
        """更新消息内容（用于流式写入完成后的更新）"""
        message = await db.get(AgentMessage, message_id)
        if message:
            message.content = content
            await db.flush()
        return message

    @staticmethod
    async def delete_messages_by_session(
        db: AsyncSession,
        session_id: int,
    ) -> int:
        """删除会话的所有消息"""
        stmt = delete(AgentMessage).where(AgentMessage.session_id == session_id)
        result = await db.execute(stmt)
        return int(result.rowcount or 0)

    # ─────────────────────────────────────────────────────────────────────────
    # Summary 操作
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    async def get_latest_summary(
        db: AsyncSession,
        session_id: int,
    ) -> Optional[AgentSessionSummary]:
        """获取最新的摘要"""
        stmt = (
            select(AgentSessionSummary)
            .where(AgentSessionSummary.session_id == session_id)
            .order_by(AgentSessionSummary.end_seq.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_summaries(
        db: AsyncSession,
        session_id: int,
        *,
        is_archived: Optional[bool] = None,
        order_by: str = "end_seq ASC",
        limit: Optional[int] = None,
    ) -> List[AgentSessionSummary]:
        """查询摘要列表 (可按 is_archived 过滤)

        order_by:
          - 'end_seq ASC' / 'end_seq DESC'
          - 'created_at ASC' / 'created_at DESC'
        """
        conds = [AgentSessionSummary.session_id == session_id]
        if is_archived is not None:
            conds.append(AgentSessionSummary.is_archived == is_archived)

        stmt = select(AgentSessionSummary).where(and_(*conds))

        # 排序
        col = AgentSessionSummary.end_seq if "end_seq" in order_by else AgentSessionSummary.created_at
        if "DESC" in order_by:
            stmt = stmt.order_by(col.desc())
        else:
            stmt = stmt.order_by(col.asc())

        if limit:
            stmt = stmt.limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def list_summaries_by_session(
        db: AsyncSession,
        session_id: int,
    ) -> List[AgentSessionSummary]:
        """获取会话的所有摘要（按 end_seq 升序）"""
        return await AIChatRepository.list_summaries(
            db, session_id, order_by="end_seq ASC"
        )

    @staticmethod
    async def create_summary(
        db: AsyncSession,
        session_id: int,
        summary: str,
        start_seq: int,
        end_seq: int,
        is_archived: bool = False,
    ) -> AgentSessionSummary:
        """创建摘要 (默认近期摘要, is_archived=False)"""
        obj = AgentSessionSummary(
            session_id=session_id,
            summary=summary,
            start_seq=start_seq,
            end_seq=end_seq,
            is_archived=is_archived,
        )
        db.add(obj)
        await db.flush()
        return obj

    @staticmethod
    async def delete_summary(
        db: AsyncSession,
        summary_id: int,
    ) -> bool:
        """按主键删除单条摘要"""
        summary = await db.get(AgentSessionSummary, summary_id)
        if summary:
            await db.delete(summary)
            await db.flush()
            return True
        return False

    @staticmethod
    async def update_summary(
        db: AsyncSession,
        summary_id: int,
        *,
        summary_text: Optional[str] = None,
        start_seq: Optional[int] = None,
        end_seq: Optional[int] = None,
        is_archived: Optional[bool] = None,
    ) -> Optional[AgentSessionSummary]:
        """更新摘要（用于历史摘要合并 / 再压缩）"""
        obj = await db.get(AgentSessionSummary, summary_id)
        if not obj:
            return None
        if summary_text is not None:
            obj.summary = summary_text
        if start_seq is not None:
            obj.start_seq = start_seq
        if end_seq is not None:
            obj.end_seq = end_seq
        if is_archived is not None:
            obj.is_archived = is_archived
        await db.flush()
        return obj

    # ─────────────────────────────────────────────────────────────────────────
    # Snapshot 操作
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    async def get_snapshot(
        db: AsyncSession,
        session_id: int,
    ) -> Optional[AgentSessionSnapshot]:
        """获取会话快照"""
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
        """创建或更新 snapshot (压缩状态机)

        字段:
          - last_summary_end_seq  上次摘要覆盖的最后一条 seq
          - recent_summary_count  当前近期摘要数量 (is_archived=false)
          - last_summary_at       上次压缩时间
          - total_summary_count   累计摘要数 (近期+历史)
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

    # ─────────────────────────────────────────────────────────────────────────
    # Message 查询扩展（压缩使用）
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    async def get_latest_seq(
        db: AsyncSession,
        session_id: int,
    ) -> Optional[int]:
        """获取会话最新一条消息的 seq (无消息返回 None)"""
        stmt = select(func.max(AgentMessage.seq)).where(
            AgentMessage.session_id == session_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_messages_range(
        db: AsyncSession,
        session_id: int,
        start_seq: int,
        end_seq: int,
    ) -> List[AgentMessage]:
        """按 seq 范围取消息 (闭区间, 按 seq ASC)"""
        stmt = (
            select(AgentMessage)
            .where(
                AgentMessage.session_id == session_id,
                AgentMessage.seq >= start_seq,
                AgentMessage.seq <= end_seq,
            )
            .order_by(AgentMessage.seq.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ─────────────────────────────────────────────────────────────────────────
    # 事务辅助
    # ─────────────────────────────────────────────────────────────────────────

    # 事务由 src/infra/database.py:get_db 统一管理（Step 2 重构）



__all__ = ["AIChatRepository"]
