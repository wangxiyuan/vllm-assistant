"""
配置管理模块
- 环境变量（.env）为基础
- ``POLLING_AREAS`` 支持 env 逗号分隔格式
"""
import os
from pathlib import Path
from typing import Optional, List, Dict
from dotenv import load_dotenv

load_dotenv()


class Config:
    """全局配置（类属性 + 环境变量覆盖）"""

    # GitHub
    GITHUB_OWNER: str = os.getenv("GITHUB_OWNER", "vllm-project")
    GITHUB_REPO: str = os.getenv("GITHUB_REPO", "vllm")
    GITHUB_PAT: str = os.getenv("VLLM_ASSISTANT_PAT", "")

    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "65536"))

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    API_KEY: str = os.getenv("API_KEY", "")
    DEBUG: bool = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")

    @classmethod
    def get_issues_url(cls, number: int) -> str:
        """Generate GitHub issue URL for a given number"""
        return f"https://github.com/{cls.GITHUB_OWNER}/{cls.GITHUB_REPO}/issues/{number}"

    @classmethod
    def get_pulls_url(cls, number: int) -> str:
        """Generate GitHub pull request URL for a given number"""
        return f"https://github.com/{cls.GITHUB_OWNER}/{cls.GITHUB_REPO}/pull/{number}"

    # DB
    BASE_DIR: Path = Path(__file__).parent.parent
    DB_PATH: Path = BASE_DIR / "data" / "vllm_assistant.db"

    # Polling
    POLLING_INTERVAL: int = int(os.getenv("POLLING_INTERVAL", "10"))
    POLLING_AREAS: List[str] = None  # type: ignore

    # Personal TODO - 去重检查默认仓库
    DEFAULT_DEDUP_REPOS: List[str] = os.getenv(
        "DEFAULT_DEDUP_REPOS", "vllm-project/vllm"
    ).split(",")

    # Personal TODO - 洞察报告异步超时（秒）
    INTELLIGENCE_REPORT_TIMEOUT: int = int(os.getenv("INTELLIGENCE_REPORT_TIMEOUT", "180"))

    # Tavily 兼容 Web Search API（用于 web 搜索工具）
    # 默认使用公益服务 https://tavily.claude-code-best.win，无需 API Key
    # 也可配置为官方 Tavily 或其他兼容服务
    TAVILY_API_URL: str = os.getenv("TAVILY_API_URL", "https://tavily.claude-code-best.win")
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")

    # ===== 代码仓库配置 =====
    # 代码仓库列表：{"vllm": "https://github.com/vllm-project/vllm.git", ...}
    REPOS: Dict[str, str] = {}

    # 代码同步间隔（分钟）
    CODE_SYNC_INTERVAL: int = int(os.getenv("CODE_SYNC_INTERVAL", "30"))

    # ===== 数据清理配置 =====
    # 社区数据保留天数（closed/merged 超过此天数将被清理）
    DATA_RETENTION_DAYS: int = int(os.getenv("DATA_RETENTION_DAYS", "90"))
    # AI 缓存保留条数上限（超过此数量时删除最旧的）
    AI_CACHE_MAX_RECORDS: int = int(os.getenv("AI_CACHE_MAX_RECORDS", "1000"))
    # 数据清理间隔（小时）
    CLEANUP_INTERVAL: int = int(os.getenv("CLEANUP_INTERVAL", "24"))

    @classmethod
    def parse_repos_config(cls) -> None:
        """从环境变量 REPOS 解析仓库配置"""
        raw = os.getenv("REPOS", "")
        if not raw:
            cls.REPOS = {}
            return

        repos = {}
        for part in raw.split(","):
            part = part.strip()
            if "=" in part:
                name, url = part.split("=", 1)
                repos[name.strip()] = url.strip()
        cls.REPOS = repos

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

    @classmethod
    def get_base_url(cls) -> str:
        return f"https://api.github.com/repos/{cls.GITHUB_OWNER}/{cls.GITHUB_REPO}"


# 初始化 POLLING_AREAS
_polling_raw = os.getenv("POLLING_AREAS", "").strip()
if _polling_raw:
    Config.POLLING_AREAS = [a.strip() for a in _polling_raw.split(",") if a.strip()]
else:
    Config.POLLING_AREAS = []

# 解析仓库配置
Config.parse_repos_config()