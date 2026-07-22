"""
配置管理模块
- 环境变量（.env）为基础
- config.yaml 可覆盖部分字段（DESIGN.md 349-371 行）
- ``POLLING_AREAS`` 支持 env（逗号分隔）或 yaml（列表）两种格式
"""
import os
from pathlib import Path
from typing import Optional, Any, List
import yaml
from dotenv import load_dotenv

load_dotenv()


class Config:
    """全局配置（类属性 + 文件/环境变量覆盖）"""

    # GitHub
    GITHUB_OWNER: str = os.getenv("GITHUB_OWNER", "vllm-project")
    GITHUB_REPO: str = os.getenv("GITHUB_REPO", "vllm")
    GITHUB_PAT: str = os.getenv("VLLM_ASSISTANT_PAT", "")

    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

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
    # DESIGN.md 360 行：polling.areas（仅同步这些领域，空=全部）
    # env 写法：POLLING_AREAS="engine,hardware"
    POLLING_AREAS: List[str] = None  # type: ignore

    # User
    USERNAME: str = os.getenv("GITHUB_USERNAME", "")

    # Personal TODO - 去重检查默认仓库（DESIGN-PERSONAL-TODO.md 7）
    DEFAULT_DEDUP_REPOS: List[str] = os.getenv(
        "DEFAULT_DEDUP_REPOS", "vllm-project/vllm"
    ).split(",")

    # Personal TODO - 洞察报告异步超时（秒）
    INTELLIGENCE_REPORT_TIMEOUT: int = int(os.getenv("INTELLIGENCE_REPORT_TIMEOUT", "180"))

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


def _flat_to_class_attrs(data: dict) -> None:
    """把 yaml/env 字典平铺到 Config 类属性"""
    # 顶层直接覆盖（注意：env 已经设过默认值，yaml 不再覆盖 env）
    for key, value in data.items():
        if not hasattr(Config, key):
            continue
        if isinstance(value, (str, int, float, bool)):
            setattr(Config, key, value)

    # 嵌套 polling.areas → POLLING_AREAS
    polling = data.get("polling") or {}
    if isinstance(polling, dict) and "areas" in polling:
        areas = polling["areas"] or []
        if isinstance(areas, list):
            Config.POLLING_AREAS = [str(a) for a in areas if a]


def _load_env_polling_areas() -> None:
    """POLLING_AREAS="engine,hardware" 形式"""
    raw = os.getenv("POLLING_AREAS", "").strip()
    if raw:
        Config.POLLING_AREAS = [a.strip() for a in raw.split(",") if a.strip()]


# 初始化默认值
if Config.POLLING_AREAS is None:
    Config.POLLING_AREAS = []


def load_config_file(path: Optional[str] = None) -> dict:
    if path is None:
        path = Path(__file__).parent.parent / "config.yaml"
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# 加载顺序：class 默认值 → yaml 覆盖 → env 覆盖
file_config = load_config_file()
_flat_to_class_attrs(file_config)
_load_env_polling_areas()
