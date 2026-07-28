"""
AI 输出缓存服务

封装 ai_cache 表的 CRUD 操作，供 review/summary/translate 等场景共享。
"""
import json
import logging
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models import AICache

logger = logging.getLogger(__name__)


class AICacheService:
    """AI 输出缓存（操作 ai_cache 表）"""

    def get(self, item_type: str, number: int, action: str):
        """读取 AI 缓存，返回 dict（旧格式）或 str（新格式）"""
        db = SessionLocal()
        try:
            row = (
                db.query(AICache)
                .filter(
                    AICache.item_type == item_type,
                    AICache.number == number,
                    AICache.action == action,
                )
                .first()
            )
            if row and row.result:
                try:
                    return json.loads(row.result)
                except (json.JSONDecodeError, TypeError):
                    return None
            return None
        finally:
            db.close()

    def set(self, item_type: str, number: int, action: str, result) -> None:
        """写入 AI 缓存（覆盖已有记录）。接受 str 或 dict。"""
        db = SessionLocal()
        try:
            row = (
                db.query(AICache)
                .filter(
                    AICache.item_type == item_type,
                    AICache.number == number,
                    AICache.action == action,
                )
                .first()
            )
            payload = json.dumps(result, ensure_ascii=False)
            if row:
                row.result = payload
                row.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
            else:
                db.add(
                    AICache(
                        item_type=item_type,
                        number=number,
                        action=action,
                        result=payload,
                    )
                )
            db.commit()
        except Exception:
            logger.exception("Failed to save AI cache")
            db.rollback()
        finally:
            db.close()

    def clear(self, item_type: str, number: int, action: str) -> None:
        """清除指定条目的 AI 缓存"""
        db = SessionLocal()
        try:
            row = (
                db.query(AICache)
                .filter(
                    AICache.item_type == item_type,
                    AICache.number == number,
                    AICache.action == action,
                )
                .first()
            )
            if row:
                db.delete(row)
                db.commit()
            return {"ok": True}
        except Exception:
            logger.exception("Error in ai_cache clear")
            db.rollback()
            raise
        finally:
            db.close()


# 全局单例
ai_cache = AICacheService()