"""
Slack 消息采集服务

通过 Slack Web API 直接采集频道消息，
存入 AIMemory 知识库（source_type="slack"），
并自动清理超过 30 天的旧数据。

认证方式（二选一）：
1. 环境变量 SLACK_TOKEN + SLACK_COOKIE（从浏览器 DevTools 获取）
2. slackdump 凭证文件（通过 slackdump workspace new 生成）
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from app.config import Config
from app.database import SessionLocal
from app.models import AIMemory, SlackConfig

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api/"


class SlackCollector:
    """Slack 消息采集器

    认证优先级：环境变量 > DB 配置
    """

    def __init__(self):
        self.token = Config.SLACK_TOKEN
        self.cookie = Config.SLACK_COOKIE
        self._session: Optional[requests.Session] = None
        self._load_db_credentials()

    def _load_db_credentials(self):
        if self.token and self.cookie:
            return
        try:
            db = SessionLocal()
            try:
                config = db.query(SlackConfig).first()
                if config and config.token and config.cookie:
                    self.token = config.token
                    self.cookie = config.cookie
            finally:
                db.close()
        except Exception:
            pass

    def _ensure_session(self) -> requests.Session:
        if self._session is not None:
            return self._session
        self._session = requests.Session()
        if self.token:
            self._session.headers.update({"Authorization": f"Bearer {self.token}"})
        if self.cookie:
            d_s = str(int(time.time()) - 10)
            self._session.headers.update({"Cookie": f"d={self.cookie}; d-s={d_s}"})
        self._session.headers.update({"Content-Type": "application/x-www-form-urlencoded"})
        return self._session

    def _api_call(self, method: str, params: dict = None) -> dict:
        s = self._ensure_session()
        resp = s.get(SLACK_API_BASE + method, params=params, timeout=30)
        data = resp.json()
        if not data.get("ok"):
            error = data.get("error", "unknown_error")
            if error == "invalid_auth":
                logger.error("Slack API: invalid auth - token or cookie expired")
            elif error == "not_in_channel":
                logger.warning(f"Slack API: bot not in channel {params.get('channel', '')}")
            else:
                logger.warning(f"Slack API error ({error}): {method}")
            return {"ok": False, "error": error}
        return data

    def has_credentials(self) -> bool:
        return bool(self.token) and bool(self.cookie)

    def list_channels(self) -> list:
        """获取所有可见频道的列表（名称 + ID）"""
        if not self.has_credentials():
            return []
        result = []
        cursor = None
        while True:
            params = {
                "limit": 200,
                "exclude_archived": True,
                "types": "public_channel,private_channel",
            }
            if cursor:
                params["cursor"] = cursor
            data = self._api_call("conversations.list", params)
            if not data.get("ok"):
                break
            for ch in data.get("channels", []):
                result.append({
                    "id": ch.get("id"),
                    "name": ch.get("name"),
                    "display": f"#{ch.get('name')}",
                    "num_members": ch.get("num_members", 0),
                    "topic": ch.get("topic", {}).get("value", "")[:100],
                    "purpose": ch.get("purpose", {}).get("value", "")[:100],
                })
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break
        return result

    def collect(self) -> dict:
        """执行一次采集：读取 SlackConfig 配置，逐个频道采集消息"""
        if not self.has_credentials():
            logger.info("Slack credentials not configured, skipping collection")
            return {"error": "credentials not configured"}

        # 验证凭证
        test = self._api_call("auth.test")
        if not test.get("ok"):
            return {"error": f"auth failed: {test.get('error', 'unknown')}"}
        logger.info(f"Slack auth ok: team={test.get('team', '')}, user={test.get('user', '')}")

        db = SessionLocal()
        try:
            config = db.query(SlackConfig).first()
            if not config or not config.channels:
                logger.info("No Slack config or channels configured, skipping collection")
                return {"error": "no channels configured"}

            channels = json.loads(config.channels) if isinstance(config.channels, str) else config.channels
            if not channels:
                return {"error": "empty channel list"}

            interval = config.collect_interval or 360
            oldest = (datetime.now() - timedelta(minutes=interval)).timestamp()
            stats = {"channels": len(channels), "total_fetched": 0, "total_stored": 0}

            for channel_name in channels:
                channel_id = self._resolve_channel_id(channel_name)
                if not channel_id:
                    logger.warning(f"Cannot resolve channel: {channel_name}, skipping")
                    continue
                fetched, stored = self._collect_channel(db, channel_id, channel_name, oldest)
                stats["total_fetched"] += fetched
                stats["total_stored"] += stored

            config.last_collect_at = datetime.now(timezone.utc).replace(tzinfo=None)
            config.total_messages = (config.total_messages or 0) + stats["total_stored"]
            config.cred_exists = True
            db.commit()

            self._cleanup_old(db)

            logger.info(f"Slack collection complete: {stats}")
            return stats
        finally:
            db.close()

    def _resolve_channel_id(self, channel_name: str) -> Optional[str]:
        """将 #general 解析为 channel ID (C...)"""
        if channel_name.startswith("C"):
            return channel_name
        data = self._api_call("conversations.list", {
            "limit": 1000,
            "types": "public_channel,private_channel",
        })
        if not data.get("ok"):
            return None
        for ch in data.get("channels", []):
            if ch.get("name") == channel_name.lstrip("#"):
                return ch.get("id")
        return None

    def _collect_channel(self, db, channel_id: str, channel_name: str, oldest: float) -> tuple:
        """采集单个频道的消息"""
        all_messages = []
        cursor = None

        while True:
            params = {
                "channel": channel_id,
                "oldest": str(oldest),
                "limit": 100,
            }
            if cursor:
                params["cursor"] = cursor

            data = self._api_call("conversations.history", params)
            if not data.get("ok"):
                return 0, 0

            messages = data.get("messages", [])
            all_messages.extend(messages)

            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor or not data.get("has_more"):
                break

        stored = 0
        for msg in all_messages:
            if self._store_message(db, channel_name, msg):
                stored += 1
        if stored:
            db.commit()

        return len(all_messages), stored

    def _resolve_user_name(self, user_id: str) -> str:
        """解析用户 ID 为显示名"""
        if not user_id or user_id.startswith("U"):
            data = self._api_call("users.info", {"user": user_id})
            if data.get("ok"):
                user = data.get("user", {})
                return user.get("real_name") or user.get("name") or user_id
        return user_id

    def _store_message(self, db, channel: str, msg: dict) -> bool:
        """将单条消息存入 AIMemory（去重）"""
        ts = msg.get("ts", "")
        if not ts:
            return False
        source_ref = f"slack:{channel}:{ts}"

        exists = db.query(AIMemory).filter(AIMemory.source_ref == source_ref).first()
        if exists:
            return False

        user_id = msg.get("user", "") or msg.get("bot_id", "unknown")
        user = self._resolve_user_name(user_id)
        text = msg.get("text", "")
        thread_ts = msg.get("thread_ts", "")

        content = f"[{channel}] {user}: {text}"
        if thread_ts:
            content += "\n> (thread reply)"

        memory = AIMemory(
            content=content,
            source_type="slack",
            source_ref=source_ref,
            tags=json.dumps(["slack"]),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(memory)
        return True

    def _cleanup_old(self, db):
        """删除超过 30 天的 Slack 消息"""
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
        deleted = db.query(AIMemory).filter(
            AIMemory.source_type == "slack",
            AIMemory.created_at < cutoff,
        ).delete(synchronize_session=False)
        if deleted:
            logger.info(f"Cleaned up {deleted} old Slack messages older than 30 days")

    def check_credential(self) -> bool:
        """检查凭证是否有效"""
        if not self.has_credentials():
            return False
        test = self._api_call("auth.test")
        return test.get("ok", False)