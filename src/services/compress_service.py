"""上下文压缩服务

按文档 step2/agent/06-context-compress.md 实现:
- 累计 N 条消息触发一次 LLM 摘要
- 1 条历史摘要 (is_archived=true) + 最多 N 条近期摘要 (is_archived=false)
- 近期超出 -> 把最旧的一条合并到历史
- 历史超阈值 -> 触发再压缩

触发判断用 seq 差值 (last_summary_end_seq), 不写消息计数器
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infra.config import get_settings
from src.models.ai_chat import AgentMessage
from src.repositories.ai_chat_repo import AIChatRepository

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────
# Prompt 模板 (硬约束字数)
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


class CompressService:
    """上下文压缩服务

    入口:
      - should_compress(db, session_id)         # 触发判断
      - maybe_compress(db, session_id)          # 自动判断并执行压缩, 返回新 summary id
      - do_compress(db, session_id)             # 强制执行压缩
    """

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
            recent = recent[1:]  # 最旧的已合并/删除
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
    # 摘要合并 / 再压缩
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

    # ────────────────────────────────────────────────────────────────────────
    # LLM 调用
    # ────────────────────────────────────────────────────────────────────────

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


# 全局单例
_compress_service: Optional[CompressService] = None


def get_compress_service() -> CompressService:
    global _compress_service
    if _compress_service is None:
        _compress_service = CompressService()
    return _compress_service


__all__ = ["CompressService", "get_compress_service"]
