"""
Slack 消息采集服务

通过 Slack Web API 直接采集频道消息，
存入 AIMemory 知识库（source_type="slack"），
并自动清理超过 30 天的旧数据。

认证方式：
- 通过前端配置页面设置 token + cookie
- 过期后自动用环境变量中的邮箱密码重新登录获取
"""
import json
import logging
import os
import re
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

    凭证从数据库 SlackConfig 表读取（通过前端配置页面设置）
    """

    def __init__(self):
        self.token = ""
        self.cookie = ""
        self._session: Optional[requests.Session] = None
        self._load_db_credentials()

    def _load_db_credentials(self):
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

    def _ensure_valid_auth(self) -> bool:
        """确保凭证有效，失效时自动刷新"""
        if not self.has_credentials():
            return False
        test = self._api_call("auth.test")
        if test.get("ok"):
            return True
        logger.info("Credentials expired, attempting refresh...")
        if self._refresh_credentials():
            return True
        return False

    def list_channels(self) -> list:
        """获取所有可见频道的列表（名称 + ID）"""
        if not self._ensure_valid_auth():
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
        if not self._ensure_valid_auth():
            return {"error": "credentials not configured or auth failed"}
        logger.info("Slack auth ok, starting collection")

        db = SessionLocal()
        try:
            config = db.query(SlackConfig).first()
            if not config or not config.channels:
                logger.info("No Slack config or channels configured, skipping collection")
                return {"error": "no channels configured"}

            channels = json.loads(config.channels) if isinstance(config.channels, str) else config.channels
            if not channels:
                return {"error": "empty channel list"}

            interval = config.collect_lookback or 1440
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

    @staticmethod
    def _clean_slack_text(text: str) -> str:
        """清洗 Slack 消息文本：将 <@U12345> 格式转为 @username，去除多余的格式标签"""
        # 将 <@U12345> 或 <@U12345|username> 转为 @username 或 @user
        text = re.sub(r'<@([A-Z0-9]+)(?:\|[^>]+)?>', r'@\1', text)
        # 将 <#C12345|channel-name> 转为 #channel-name
        text = re.sub(r'<#[A-Z0-9]+\|([^>]+)>', r'#\1', text)
        # 将 <http://...|text> 转为 text (url)
        text = re.sub(r'<https?://[^|>]+\|([^>]+)>', r'\1', text)
        # 去除孤立的 URL 尖括号 <https://...>
        text = re.sub(r'<(https?://[^>]+)>', r'\1', text)
        return text

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
        text = self._clean_slack_text(msg.get("text", ""))
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

    def _refresh_credentials(self) -> bool:
        """用环境变量中的邮箱密码重新登录，获取新 token 和 cookie 并存入数据库"""
        email = Config.SLACK_EMAIL
        password = Config.SLACK_PASSWORD
        if not email or not password:
            logger.warning("SLACK_EMAIL / SLACK_PASSWORD not configured, cannot refresh credentials")
            return False

        ws = "vllm-dev"
        try:
            s = requests.Session()
            s.headers.update({
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            })

            r = s.get(f"https://{ws}.slack.com/sign_in_with_password", timeout=15)
            m = re.search(r'crumbValue&quot;:&quot;(.*?)&quot;', r.text)
            if not m:
                logger.error(f"Failed to extract crumb from signin page, status={r.status_code}")
                logger.error(f"Signin page snippet: {r.text[:2000]}")
                return False
            crumb = m.group(1).encode().decode("unicode_escape")

            login_data = {
                "signin": "1", "redir": "", "has_remember": "true",
                "crumb": crumb, "remember": "remember",
                "email": email, "password": password,
            }
            login_resp = s.post(f"https://{ws}.slack.com/sign_in_with_password", data=login_data,
                   allow_redirects=True, timeout=15)

            logger.error(f"Login response status: {login_resp.status_code}")
            logger.error(f"Login response URL: {login_resp.url}")
            logger.error(f"Cookies after login: {dict(s.cookies)}")

            d_cookie = s.cookies.get("d")
            if not d_cookie:
                # 登录失败时尝试提取错误信息
                err_msg = "unknown"
                for err_pat in [
                    r'class="[^"]*error[^"]*"[^>]*>(.*?)<',
                    r'<p[^>]*class="[^"]*error[^"]*"[^>]*>(.*?)<',
                    r'invalid_email_or_password',
                    r'account_not_found',
                    r'signin_bad_password',
                ]:
                    em = re.search(err_pat, login_resp.text, re.DOTALL)
                    if em:
                        err_msg = em.group(1).strip()[:200] if em.groups() else em.group(0)
                        break
                logger.error(f"Login failed: {err_msg} (status={login_resp.status_code}, url={login_resp.url})")
                return False

            r2 = s.get(f"https://{ws}.slack.com/", timeout=15)
            m2 = re.search(r'xoxc-[a-zA-Z0-9-]+', r2.text)
            if not m2:
                logger.error("No xoxc token found after login")
                return False
            new_token = m2.group(0)

            new_cookie = d_cookie
            now = datetime.now(timezone.utc).replace(tzinfo=None)

            db = SessionLocal()
            try:
                config = db.query(SlackConfig).first()
                if not config:
                    config = SlackConfig(channels="[]", collect_interval=360)
                    db.add(config)
                config.token = new_token
                config.cookie = new_cookie
                config.cred_exists = True
                config.last_refresh_at = now
                db.commit()
            finally:
                db.close()

            self.token = new_token
            self.cookie = new_cookie
            self._session = None
            logger.info("Credentials refreshed successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to refresh credentials: {e}")
            return False