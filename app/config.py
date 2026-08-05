"""
配置管理模块
- 环境变量（.env）为基础
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Config:
    """全局配置（类属性 + 环境变量覆盖）"""

    # GitHub
    GITHUB_PAT: str = os.getenv("VLLM_ASSISTANT_PAT", "")

    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "1048576"))

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    API_KEY: str = os.getenv("API_KEY", "")
    DEBUG: bool = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")

    # DB
    BASE_DIR: Path = Path(__file__).parent.parent
    DB_PATH: Path = BASE_DIR / "data" / "vllm_assistant.db"

    # Polling
    POLLING_INTERVAL: int = int(os.getenv("POLLING_INTERVAL", "10"))
    GITHUB_SYNC_ENABLED: bool = os.getenv("GITHUB_SYNC_ENABLED", "true").lower() in ("1", "true", "yes")

    # Tavily 兼容 Web Search API（用于 web 搜索工具）
    # 默认使用公益服务 https://tavily.claude-code-best.win，无需 API Key
    # 也可配置为官方 Tavily 或其他兼容服务
    TAVILY_API_URL: str = os.getenv("TAVILY_API_URL", "https://tavily.claude-code-best.win")
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")

    # ===== 数据清理配置 =====
    # 社区数据保留天数（closed/merged 超过此天数将被清理）
    DATA_RETENTION_DAYS: int = int(os.getenv("DATA_RETENTION_DAYS", "90"))
    # AI 缓存保留条数上限（超过此数量时删除最旧的）
    AI_CACHE_MAX_RECORDS: int = int(os.getenv("AI_CACHE_MAX_RECORDS", "1000"))
    # 数据清理间隔（小时）
    CLEANUP_INTERVAL: int = int(os.getenv("CLEANUP_INTERVAL", "24"))

    # ===== Slack 采集配置 =====
    # 凭证通过前端配置页面动态设置
    # 邮箱密码用于凭证过期后自动刷新
    SLACK_EMAIL: str = os.getenv("SLACK_EMAIL", "")
    SLACK_PASSWORD: str = os.getenv("SLACK_PASSWORD", "")

    @classmethod
    def validate(cls) -> bool:
        if not cls.GITHUB_PAT:
            raise ValueError("VLLM_ASSISTANT_PAT is required in environment variables")
        return True

    @classmethod
    def get_github_headers(cls) -> dict:
        return {
            "Authorization": f"token {cls.GITHUB_PAT}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }