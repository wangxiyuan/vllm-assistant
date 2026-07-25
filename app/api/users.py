"""
Users API - 用户管理（非租户，仅用于责任人关联）
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

logger = logging.getLogger(__name__)
router = APIRouter()


class UserCreate(BaseModel):
    name: str
    github_id: str = ""


class UserUpdate(BaseModel):
    name: str = ""
    github_id: str = ""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("")
async def list_users(db: Session = Depends(get_db)):
    """获取用户列表"""
    users = db.query(User).order_by(User.name).all()
    return {"users": [u.to_dict() for u in users]}


@router.post("", status_code=201)
async def create_user(req: UserCreate, db: Session = Depends(get_db)):
    """创建用户"""
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    user = User(
        name=req.name.strip(),
        github_id=req.github_id.strip() or None,
        created_at=_utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.to_dict()


@router.put("/{user_id}")
async def update_user(user_id: int, req: UserUpdate, db: Session = Depends(get_db)):
    """更新用户"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if req.name.strip():
        user.name = req.name.strip()
    if req.github_id is not None:
        user.github_id = req.github_id.strip() or None
    db.commit()
    db.refresh(user)
    return user.to_dict()


@router.delete("/{user_id}")
async def delete_user(user_id: int, db: Session = Depends(get_db)):
    """删除用户"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    return {"deleted": True}