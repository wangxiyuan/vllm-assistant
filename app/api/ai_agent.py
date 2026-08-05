"""
AI Agent API 路由

不做业务逻辑，只做转发。
"""
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.config import Config
from app.database import SessionLocal
from app.models import AIChatSession, AIChatMessage, QuickPrompt
from app.schemas import QuickPromptCreate, QuickPromptUpdate, QuickPromptResponse
from app.services.agent_runner import AgentRunner

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_api_key():
    if not Config.OPENAI_API_KEY:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not configured")


# ======================================================================
# 请求/响应模型
# ======================================================================


class ChatRequest(BaseModel):
    """对话请求"""
    messages: List[dict]
    session_id: Optional[str] = None  # 会话 ID，用于持久化
    tools: Optional[List[str]] = None
    stream: bool = True
    system_prompt: Optional[str] = None


class ChatMessage(BaseModel):
    role: str
    content: str


class MemoryCreateRequest(BaseModel):
    """手动添加知识"""
    content: str
    source_type: str = "manual"
    source_ref: Optional[str] = None
    tags: Optional[List[str]] = None


# ======================================================================
# 对话 API
# ======================================================================


@router.post("/chat")
async def chat(request: ChatRequest, fastapi_request: Request):
    """AI Agent 对话（streaming SSE）

    请求体示例：
    ```json
    {
      "messages": [{"role": "user", "content": "..."}],
      "session_id": "xxx",
      "tools": ["github", "knowledge", "code"],
      "stream": true
    }
    ```

    `session_id` 指定会话 ID，用于持久化对话历史。
    客户端断开 / 主动 abort 时，后端会在下一次 yield 时检测到并退出 agent 循环。
    """
    _require_api_key()

    from fastapi.responses import StreamingResponse

    async def event_stream():
        try:
            runner = AgentRunner()
        except Exception as e:
            logger.exception("Failed to create AgentRunner")
            yield f"data: {json.dumps({'type': 'error', 'data': f'AI 服务初始化失败: {e}'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'data': None}, ensure_ascii=False)}\n\n"
            return

        # 如果传了 session_id，先存 user 消息
        if request.session_id:
            _sync_and_save_user_message(request.session_id, request.messages)

        try:
            assistant_content = None
            chat_iter = runner.chat(
                messages=[m.dict() if hasattr(m, 'dict') else m for m in request.messages],
                tools=request.tools,
                stream=request.stream,
                system_prompt=request.system_prompt,
                session_id=request.session_id,
            )
            async for event in chat_iter:
                # 客户端断开检测：用户删对话 / 关页面 / 点停止按钮都会触发
                if await fastapi_request.is_disconnected():
                    logger.info("Agent chat aborted: client disconnected (session=%s)", request.session_id)
                    # 显式关闭 agent 迭代器，触发 CancelledError 中断 tool execution
                    await chat_iter.aclose()
                    break

                # 记录最终 assistant 回复
                if event["type"] == "token":
                    if assistant_content is None:
                        assistant_content = event["data"]
                    else:
                        assistant_content += event["data"]

                # 在 done 事件发出前保存 assistant 回复并更新会话标题，
                # 避免前端 loadSessions() 与后端保存操作产生竞态条件
                if event["type"] == "done" and request.session_id and assistant_content:
                    _save_assistant_message(request.session_id, assistant_content)

                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("Error during AI chat streaming")
            yield f"data: {json.dumps({'type': 'error', 'data': f'AI 响应异常: {e}'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'data': None}, ensure_ascii=False)}\n\n"
        finally:
            await runner.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sync_and_save_user_message(session_id: str, messages: List[dict]):
    """同步 DB 消息与前端历史：截断+插入保持与前端一致"""
    from app.database import SessionLocal
    from app.models import AIChatMessage, AIChatSession

    db = SessionLocal()
    try:
        user_msgs = [m for m in messages if m.get("role") == "user"]

        existing = (
            db.query(AIChatMessage)
            .filter(AIChatMessage.session_id == session_id)
            .order_by(AIChatMessage.id)
            .all()
        )
        existing_users = [m for m in existing if m.role == "user"]

        if not user_msgs:
            return

        # 找到 DB 中需要保留的截止点：与前端 user 消息数对齐
        if len(existing_users) >= len(user_msgs):
            cutoff_user = existing_users[len(user_msgs) - 1]
            # 用户编辑了同一条消息 → 更新内容
            if cutoff_user.content != user_msgs[-1]["content"]:
                cutoff_user.content = user_msgs[-1]["content"]
            # 删除该 user 之后的所有消息（老的 assistant 回复等）
            db.query(AIChatMessage).filter(
                AIChatMessage.session_id == session_id,
                AIChatMessage.id > cutoff_user.id,
            ).delete()
        else:
            # 新的 user 消息：前端比 DB 多，只插入最后一条
            last_user = user_msgs[-1]
            db.add(AIChatMessage(
                session_id=session_id,
                role="user",
                content=last_user["content"],
            ))
        # 用 count 同步 message_count
        session = db.query(AIChatSession).filter(AIChatSession.id == session_id).first()
        if session:
            session.message_count = db.query(AIChatMessage).filter(
                AIChatMessage.session_id == session_id
            ).count()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to sync/save user message")
    finally:
        db.close()


def _save_assistant_message(session_id: str, content: str):
    """将 assistant 回复存入数据库"""
    from app.database import SessionLocal
    from app.models import AIChatSession, AIChatMessage

    db = SessionLocal()
    try:
        db.add(AIChatMessage(
            session_id=session_id,
            role="assistant",
            content=content,
        ))
        # 更新会话信息
        session = db.query(AIChatSession).filter(AIChatSession.id == session_id).first()
        if session:
            from datetime import datetime, timezone
            session.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            # 自动生成标题（取第一条 user 消息前 20 字）
            if session.title == "新对话":
                first_user = db.query(AIChatMessage).filter(
                    AIChatMessage.session_id == session_id,
                    AIChatMessage.role == "user",
                ).order_by(AIChatMessage.created_at.asc()).first()
                if first_user:
                    title = first_user.content[:20]
                    if len(first_user.content) > 20:
                        title += "..."
                    session.title = title
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to save assistant message")
    finally:
        db.close()


# ======================================================================
# 知识库管理 API
# ======================================================================


@router.get("/memories")
async def list_memories(
    q: str = Query("", description="搜索关键词"),
    tags: str = Query("", description="标签过滤，逗号分隔"),
    source_type: str = Query("", description="来源类型过滤，逗号分隔多个类型"),
    top_k: int = Query(5, description="搜索/列表返回数量"),
    # 分页参数（用于按 source_type 列表浏览）
    offset: int = Query(0, description="分页偏移量"),
    limit: int = Query(20, description="分页条数"),
    list_by_type: Optional[str] = Query(None, description="按 source_type 分页列出，''=全部，None=不分页"),
):
    """搜索/浏览知识库

    四种模式：
    1. list_by_type 非 None → 按 source_type 分页列出（''=全部，支持 q 关键词搜索）
    2. q 非空 → FTS5 全文检索
    3. tags 非空 → 按标签过滤
    4. 默认 → 返回最新条目
    """
    from app.services.memory_service import MemoryService

    mem = MemoryService()

    # 模式 1：分页模式
    if list_by_type is not None:
        if list_by_type:
            return mem.list_by_source_type(
                source_type=list_by_type,
                offset=offset,
                limit=limit,
                query=q,
            )
        # list_by_type="" 表示全部
        from app.database import SessionLocal
        from app.models import AIMemory

        db = SessionLocal()
        try:
            base = db.query(AIMemory).filter(AIMemory.is_stale == False)
            if q.strip():
                like = f"%{q.strip()}%"
                base = base.filter(
                    AIMemory.content.like(like) | AIMemory.source_ref.like(like)
                )
            total = base.count()
            entries = base.order_by(AIMemory.updated_at.desc()).offset(offset).limit(limit).all()
            results = [{
                "id": e.id,
                "content": e.content,
                "source_type": e.source_type,
                "source_ref": e.source_ref,
                "tags": json.loads(e.tags) if e.tags else [],
                "updated_at": e.updated_at.isoformat() + "Z" if e.updated_at else None,
            } for e in entries]
            return {
                "results": results,
                "total": total,
                "offset": offset,
                "limit": limit,
                "has_more": (offset + limit) < total,
            }
        finally:
            db.close()

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    st_list = [s.strip() for s in source_type.split(",") if s.strip()] if source_type else None

    if q.strip():
        results = mem.recall(query=q, top_k=top_k, tags=tag_list, source_types=st_list)
    elif tag_list:
        results = mem.list_by_tags(tags=tag_list, top_k=top_k)
    else:
        # 无搜索条件，返回最新条目
        from app.database import SessionLocal
        from app.models import AIMemory

        db = SessionLocal()
        try:
            entries = db.query(AIMemory).filter(AIMemory.is_stale == False).order_by(
                AIMemory.updated_at.desc()
            ).limit(top_k).all()
            results = [{
                "id": e.id,
                "content": e.content[:300],
                "source_type": e.source_type,
                "source_ref": e.source_ref,
                "tags": json.loads(e.tags) if e.tags else [],
                "updated_at": e.updated_at.isoformat() + "Z" if e.updated_at else None,
            } for e in entries]
        finally:
            db.close()

    return {"results": results, "total": len(results)}


@router.post("/memories")
async def create_memory(request: MemoryCreateRequest):
    """手动添加知识条目"""
    from app.services.memory_service import MemoryService

    mem = MemoryService()
    mem_id = mem.remember(
        content=request.content,
        source_type=request.source_type,
        source_ref=request.source_ref,
        tags=request.tags,
    )
    if mem_id:
        return {"id": mem_id, "status": "created"}
    raise HTTPException(status_code=500, detail="Failed to create memory")


@router.delete("/memories/by-source")
async def delete_memories_by_source(request: Request):
    """按 source_ref 前缀物理删除知识条目

    用于删除文章/报告/会话时同步清理关联的知识库内容。
    使用 :: 代替 # 传递（URL 中 # 会被当做 fragment 截断）。
    """
    source_ref_prefix = request.query_params.get("source_ref_prefix", "")
    if not source_ref_prefix:
        raise HTTPException(status_code=422, detail="source_ref_prefix is required")
    prefix = source_ref_prefix.replace("::", "#")

    from app.services.memory_service import MemoryService

    mem = MemoryService()
    count = mem.forget_by_source_ref_prefix(prefix, hard_delete=True)
    return {"status": "deleted", "count": count}


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: int):
    """物理删除知识条目"""
    from app.services.memory_service import MemoryService

    mem = MemoryService()
    success = mem.forget(memory_id, hard_delete=True)
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"status": "deleted"}


@router.get("/memories/stats")
async def memory_stats():
    """获取知识库统计"""
    from app.services.memory_service import MemoryService

    mem = MemoryService()
    return mem.get_stats()


# ======================================================================
# 会话管理 API
# ======================================================================


@router.get("/sessions")
async def list_sessions():
    """获取会话列表（按 updated_at 倒序）"""
    from app.database import SessionLocal
    from app.models import AIChatSession, AIChatMessage
    from sqlalchemy import func

    db = SessionLocal()
    try:
        count_subq = db.query(
            AIChatMessage.session_id,
            func.count(AIChatMessage.id).label("cnt")
        ).group_by(AIChatMessage.session_id).subquery()

        sessions = db.query(
            AIChatSession,
            func.coalesce(count_subq.c.cnt, 0).label("real_count")
        ).outerjoin(
            count_subq, AIChatSession.id == count_subq.c.session_id
        ).order_by(AIChatSession.updated_at.desc()).limit(50).all()

        return {
            "sessions": [
                {
                    "id": s.AIChatSession.id,
                    "title": s.AIChatSession.title,
                    "message_count": s.real_count,
                    "created_at": s.AIChatSession.created_at.isoformat() + "Z" if s.AIChatSession.created_at else None,
                    "updated_at": s.AIChatSession.updated_at.isoformat() + "Z" if s.AIChatSession.updated_at else None,
                }
                for s in sessions
            ]
        }
    finally:
        db.close()


@router.post("/sessions")
async def create_session():
    """创建新会话"""
    from app.database import SessionLocal
    from app.models import AIChatSession
    from datetime import datetime, timezone

    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db = SessionLocal()
    try:
        db.add(AIChatSession(id=session_id, title="新对话", created_at=now, updated_at=now))
        db.commit()
        return {"id": session_id, "title": "新对话", "message_count": 0, "created_at": now.isoformat() + "Z", "updated_at": now.isoformat() + "Z"}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create session")
    finally:
        db.close()


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话及其所有消息"""
    from app.database import SessionLocal
    from app.models import AIChatSession, AIChatMessage

    db = SessionLocal()
    try:
        session = db.query(AIChatSession).filter(AIChatSession.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        db.query(AIChatMessage).filter(AIChatMessage.session_id == session_id).delete()
        db.delete(session)
        db.commit()
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete session")
    finally:
        db.close()


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    """获取会话消息列表"""
    from app.database import SessionLocal
    from app.models import AIChatMessage

    db = SessionLocal()
    try:
        messages = db.query(AIChatMessage).filter(
            AIChatMessage.session_id == session_id
        ).order_by(AIChatMessage.created_at.asc()).all()
        return {
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "created_at": m.created_at.isoformat() + "Z" if m.created_at else None,
                }
                for m in messages
            ]
        }
    finally:
        db.close()


@router.put("/sessions/{session_id}/title")
async def update_session_title(session_id: str, request: dict):
    """更新会话标题"""
    from app.database import SessionLocal
    from app.models import AIChatSession

    title = request.get("title", "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")

    db = SessionLocal()
    try:
        session = db.query(AIChatSession).filter(AIChatSession.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        session.title = title
        db.commit()
        return {"status": "updated"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update title")
    finally:
        db.close()


# ============================================================
# Quick Prompts — 常用提示 CRUD
# ============================================================

@router.get("/quick-prompts", response_model=List[QuickPromptResponse])
def list_quick_prompts():
    """列出所有常用提示"""
    db = SessionLocal()
    try:
        prompts = db.query(QuickPrompt).order_by(QuickPrompt.sort_order, QuickPrompt.id).all()
        return [
            QuickPromptResponse(
                id=p.id, text=p.text, sort_order=p.sort_order,
                created_at=p.created_at.isoformat() + "Z" if p.created_at else None,
                updated_at=p.updated_at.isoformat() + "Z" if p.updated_at else None,
            )
            for p in prompts
        ]
    finally:
        db.close()


@router.post("/quick-prompts", response_model=QuickPromptResponse)
def create_quick_prompt(req: QuickPromptCreate):
    """创建常用提示"""
    db = SessionLocal()
    try:
        max_order = db.query(QuickPrompt).count()
        prompt = QuickPrompt(text=req.text, sort_order=max_order)
        db.add(prompt)
        db.commit()
        db.refresh(prompt)
        return QuickPromptResponse(
            id=prompt.id, text=prompt.text, sort_order=prompt.sort_order,
            created_at=prompt.created_at.isoformat() + "Z" if prompt.created_at else None,
            updated_at=prompt.updated_at.isoformat() + "Z" if prompt.updated_at else None,
        )
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create prompt")
    finally:
        db.close()


@router.put("/quick-prompts/{prompt_id}", response_model=QuickPromptResponse)
def update_quick_prompt(prompt_id: int, req: QuickPromptUpdate):
    """更新常用提示"""
    db = SessionLocal()
    try:
        prompt = db.query(QuickPrompt).filter(QuickPrompt.id == prompt_id).first()
        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt not found")
        if req.text is not None:
            prompt.text = req.text
        if req.sort_order is not None:
            prompt.sort_order = req.sort_order
        db.commit()
        db.refresh(prompt)
        return QuickPromptResponse(
            id=prompt.id, text=prompt.text, sort_order=prompt.sort_order,
            created_at=prompt.created_at.isoformat() + "Z" if prompt.created_at else None,
            updated_at=prompt.updated_at.isoformat() + "Z" if prompt.updated_at else None,
        )
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update prompt")
    finally:
        db.close()


@router.delete("/quick-prompts/{prompt_id}")
def delete_quick_prompt(prompt_id: int):
    """删除常用提示"""
    db = SessionLocal()
    try:
        prompt = db.query(QuickPrompt).filter(QuickPrompt.id == prompt_id).first()
        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt not found")
        db.delete(prompt)
        db.commit()
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete prompt")
    finally:
        db.close()