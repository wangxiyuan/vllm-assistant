"""
Comments API - 多态评论管理
对应 docs/comments-design.md
"""
import logging
import markdown
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Comment, Article, IntelligenceReport, User

logger = logging.getLogger(__name__)
router = APIRouter()


class CommentCreate(BaseModel):
    target_type: str
    target_id: int
    content: str
    user_id: Optional[int] = None


class CommentUpdate(BaseModel):
    content: str


ALLOWED_TARGET_TYPES = ("article", "report")


def _render_markdown(text: str) -> str:
    html = markdown.markdown(text, extensions=["fenced_code", "codehilite", "tables"])
    html = html.replace("<script>", "&lt;script&gt;").replace("</script>", "&lt;/script&gt;")
    html = html.replace("<iframe", "&lt;iframe").replace("</iframe>", "&lt;/iframe&gt;")
    return html


def _verify_target_exists(target_type: str, target_id: int, db: Session):
    if target_type == "article":
        obj = db.query(Article).filter(Article.id == target_id).first()
    elif target_type == "report":
        obj = db.query(IntelligenceReport).filter(IntelligenceReport.id == target_id).first()
    else:
        raise HTTPException(status_code=400, detail=f"Invalid target_type: {target_type}")
    if not obj:
        raise HTTPException(status_code=404, detail=f"{target_type} not found")


@router.get("")
async def list_comments(
    target_type: str = Query(...),
    target_id: int = Query(...),
    db: Session = Depends(get_db),
):
    if target_type not in ALLOWED_TARGET_TYPES:
        raise HTTPException(status_code=400, detail=f"target_type must be one of {ALLOWED_TARGET_TYPES}")
    comments = db.query(Comment).filter(
        Comment.target_type == target_type,
        Comment.target_id == target_id,
    ).order_by(Comment.created_at.asc()).all()
    return {"comments": [c.to_dict() for c in comments]}


@router.post("")
async def create_comment(req: CommentCreate, db: Session = Depends(get_db)):
    if req.target_type not in ALLOWED_TARGET_TYPES:
        raise HTTPException(status_code=400, detail=f"target_type must be one of {ALLOWED_TARGET_TYPES}")
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    if len(content) > 2000:
        raise HTTPException(status_code=400, detail="Content too long (max 2000 characters)")

    _verify_target_exists(req.target_type, req.target_id, db)

    if req.user_id is not None:
        user = db.query(User).filter(User.id == req.user_id).first()
        if not user:
            raise HTTPException(status_code=400, detail="User not found")

    rendered_html = _render_markdown(content)

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    comment = Comment(
        target_type=req.target_type,
        target_id=req.target_id,
        user_id=req.user_id,
        content=content,
        rendered_html=rendered_html,
        created_at=now,
        updated_at=now,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment.to_dict()


@router.put("/{comment_id}")
async def update_comment(comment_id: int, req: CommentUpdate, db: Session = Depends(get_db)):
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    if len(content) > 2000:
        raise HTTPException(status_code=400, detail="Content too long (max 2000 characters)")

    comment.content = content
    comment.rendered_html = _render_markdown(content)
    from datetime import datetime, timezone
    comment.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(comment)
    return comment.to_dict()


@router.delete("/{comment_id}")
async def delete_comment(comment_id: int, db: Session = Depends(get_db)):
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    db.delete(comment)
    db.commit()
    return {"deleted": True, "id": comment_id}