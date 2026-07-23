"""
SQLite数据库管理模块
仅负责 engine、Session、Base、get_db 工厂。
模型定义在 app/models.py（DESIGN.md 312 行要求拆分）。
"""
import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import Config
from app.models import Base

os.makedirs(Config.DB_PATH.parent, exist_ok=True)

engine = create_engine(f"sqlite:///{Config.DB_PATH}", echo=False)

# 启用外键约束（SQLite 默认不启用）
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)


def get_db():
    """获取数据库会话（FastAPI 依赖注入用）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
