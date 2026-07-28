"""AI Chat 路由

接口设计：
- GET    /sessions                  # 列表
- DELETE /sessions/{id}             # 删除
- POST   /messages/stream           # 发消息（body 传 session_id）
- GET    /messages?session_id={id}  # 消息历史
"""
import json
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.dependencies import get_db
from src.app.context import get_user_id
from src.app import response as R
from src.services.ai_chat_service import get_ai_chat_service
from src.app.schemas.ai_chat import (
    SessionListRequest,
    ChatRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai/chat", tags=["AI Chat"])


# ═══════════════════════════════════════════════════════════════════════════════
# Session 管理
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/sessions")
async def list_sessions(
    page_num: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """查询会话列表"""
    user_id = get_user_id()
    request = SessionListRequest(
        page_num=page_num,
        page_size=page_size,
    )
    service = get_ai_chat_service()
    result = await service.list_sessions(db, user_id, request)
    return R.query_resp(result)


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除会话"""
    user_id = get_user_id()
    service = get_ai_chat_service()
    result = await service.delete_session(db, session_id)
    if not result:
        return R.not_found_resp("会话不存在")
    return R.success_resp(msg="会话已删除")


# ═══════════════════════════════════════════════════════════════════════════════
# Message 管理
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/messages")
async def list_messages(
    session_id: int = Query(..., description="会话ID"),
    page_num: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """查询会话消息列表"""
    service = get_ai_chat_service()
    result = await service.list_messages(db, session_id, page_num, page_size)
    return R.query_resp(result)


@router.post("/messages/stream")
async def chat_stream(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """流式对话接口

    - session_id 为空/0：自动创建新会话
    - session_id 有值：在指定会话中继续对话

    SSE 事件格式：
    - event: session, data: {"id": 1, "title": "..."}    # 仅新建会话时
    - event: content, data: {"content": "...", "messageId": 123}
    - event: done, data: {"messageId": 456, "content": "..."}
    - event: error, data: {"message": "错误信息"}
    """
    logger.info(f"[ChatStream] 收到请求: message={request.message!r}, session_id={request.session_id}")
    user_id = get_user_id()
    service = get_ai_chat_service()

    async def event_generator():
        try:
            logger.info(f"[ChatStream] 开始生成事件流, user_id={user_id}")
            async for event in service.stream_chat(
                db, user_id, request.message, request.session_id
            ):
                logger.info(f"[ChatStream] 发送事件: event={event['event']}, data={event['data']}")
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
            logger.info("[ChatStream] 事件流结束")
        except Exception as e:
            logger.error(f"[ChatStream] 生成事件时出错: {e}", exc_info=True)
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]
