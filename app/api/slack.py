"""
Slack API - Slack 采集配置管理
"""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AIMemory, SlackConfig, _iso_utc

logger = logging.getLogger(__name__)
router = APIRouter()


class SlackConfigUpdate(BaseModel):
    token: str = ""
    cookie: str = ""
    channels: list[str] = []
    collect_interval: int = 360
    collect_lookback: int = 1440


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_or_create_config(db: Session) -> SlackConfig:
    config = db.query(SlackConfig).first()
    if not config:
        config = SlackConfig(
            channels=json.dumps([]),
            collect_interval=360,
            created_at=_utcnow(),
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


@router.get("/config")
async def get_slack_config(db: Session = Depends(get_db)):
    """获取 Slack 配置"""
    config = _get_or_create_config(db)
    return config.to_dict()


@router.put("/config")
async def update_slack_config(req: SlackConfigUpdate, db: Session = Depends(get_db)):
    """更新 Slack 配置（含 token/cookie）"""
    config = _get_or_create_config(db)
    if req.token:
        config.token = req.token
    if req.cookie:
        config.cookie = req.cookie
    config.channels = json.dumps(req.channels)
    config.collect_interval = req.collect_interval
    config.collect_lookback = req.collect_lookback or 1440
    config.cred_exists = bool(req.token and req.cookie)
    config.updated_at = _utcnow()
    db.commit()
    db.refresh(config)
    return config.to_dict()


@router.post("/config/channels")
async def add_channel(channel_data: dict, db: Session = Depends(get_db)):
    """新增一个频道"""
    channel = channel_data.get("channel", "").strip()
    if not channel:
        raise HTTPException(status_code=400, detail="channel is required")
    if not channel.startswith("#"):
        raise HTTPException(status_code=400, detail="channel must start with #")

    config = _get_or_create_config(db)
    channels = json.loads(config.channels) if isinstance(config.channels, str) else (config.channels or [])
    if channel in channels:
        raise HTTPException(status_code=400, detail=f"channel {channel} already exists")
    channels.append(channel)
    config.channels = json.dumps(channels)
    config.updated_at = _utcnow()
    db.commit()
    return config.to_dict()


@router.delete("/config/channels/{channel:path}")
async def delete_channel(channel: str, db: Session = Depends(get_db)):
    """删除一个频道"""
    config = _get_or_create_config(db)
    channels = json.loads(config.channels) if isinstance(config.channels, str) else (config.channels or [])
    if channel not in channels:
        raise HTTPException(status_code=404, detail=f"channel {channel} not found")
    channels.remove(channel)
    config.channels = json.dumps(channels)
    config.updated_at = _utcnow()
    db.commit()
    return config.to_dict()


@router.get("/status")
async def get_slack_status(db: Session = Depends(get_db)):
    """获取 Slack 采集状态"""
    from app.services.slack_collector import SlackCollector
    collector = SlackCollector()
    cred_exists = collector.has_credentials()
    config = _get_or_create_config(db)
    total = db.query(AIMemory).filter(AIMemory.source_type == "slack").count()
    cred_valid = collector.check_credential() if cred_exists else False
    return {
        "cred_exists": cred_exists or config.cred_exists or False,
        "cred_valid": cred_valid,
        "last_collect_at": _iso_utc(config.last_collect_at),
        "total_messages": total,
        "collect_interval": config.collect_interval or 360,
        "collect_lookback": config.collect_lookback or 1440,
        "last_refresh_at": _iso_utc(config.last_refresh_at),
    }


@router.get("/channels")
async def list_slack_channels():
    """获取 Slack 工作区所有可见频道列表"""
    from app.services.slack_collector import SlackCollector
    collector = SlackCollector()
    channels = collector.list_channels()
    return {"channels": channels}


@router.post("/collect")
async def trigger_collect(db: Session = Depends(get_db)):
    """手动触发一次采集"""
    from app.services.slack_collector import SlackCollector
    collector = SlackCollector()
    stats = collector.collect()
    return stats


@router.post("/refresh-token")
async def refresh_slack_token(db: Session = Depends(get_db)):
    """手动触发凭证刷新"""
    from app.services.slack_collector import SlackCollector
    collector = SlackCollector()
    ok = collector._refresh_credentials()
    if ok:
        config = _get_or_create_config(db)
        return {"ok": True, **config.to_dict()}
    return {"ok": False, "error": "refresh failed, check SLACK_EMAIL / SLACK_PASSWORD in .env"}


@router.post("/test-auth")
async def test_auth(req: SlackConfigUpdate, db: Session = Depends(get_db)):
    """测试凭证是否有效"""
    import requests, time
    token = req.token or ""
    cookie = req.cookie or ""
    if not token or not cookie:
        raise HTTPException(status_code=400, detail="token and cookie are required")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    s.headers.update({"Cookie": f"d={cookie}; d-s={str(int(time.time()) - 10)}"})
    try:
        resp = s.get("https://slack.com/api/auth.test", timeout=15)
        data = resp.json()
        if data.get("ok"):
            return {"ok": True, "user": data.get("user"), "team": data.get("team")}
        return {"ok": False, "error": data.get("error", "unknown")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.delete("/data")
async def clear_slack_data(db: Session = Depends(get_db)):
    """清除所有 Slack 知识库数据"""
    deleted = db.query(AIMemory).filter(
        AIMemory.source_type == "slack"
    ).delete(synchronize_session=False)
    config = _get_or_create_config(db)
    config.total_messages = 0
    db.commit()
    return {"deleted": deleted}