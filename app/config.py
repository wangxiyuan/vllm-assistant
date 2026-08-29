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

    # ===== Agent (OpenAI Agents SDK) 配置 =====
    # 对接自建 LLM（上下文 1M）无成本，放宽轮次预算，避免深度调研因轮次上限中断
    AGENT_MAX_TURNS: int = int(os.getenv("AGENT_MAX_TURNS", "100"))
    # 报告生成：搜索阶段独立轮次预算（之前误把仓库数当轮次，导致每阶段仅 3-4 轮）
    AGENT_SEARCH_TURNS: int = int(os.getenv("AGENT_SEARCH_TURNS", "20"))
    AGENT_TOOL_OUTPUT_LIMIT: int = int(os.getenv("AGENT_TOOL_OUTPUT_LIMIT", "30000"))

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

    # ===== AI 筛选规则（总览页）=====
    # 分诊定时任务间隔（分钟）；仅当有新增条目时才会实际调用 LLM
    AI_TRIAGE_INTERVAL: int = int(os.getenv("AI_TRIAGE_INTERVAL", "30"))
    # 单轮分诊 LLM 输出上限；命中多时 JSON 会被截断导致解析重试，默认给足余量
    AI_TRIAGE_MAX_TOKENS: int = int(os.getenv("AI_TRIAGE_MAX_TOKENS", "8192"))
    # 单条规则单轮分诊的候选条目上限
    AI_TRIAGE_CANDIDATE_LIMIT: int = int(os.getenv("AI_TRIAGE_CANDIDATE_LIMIT", "100"))
    # 手动"重新筛选"时回看的天数窗口
    AI_TRIAGE_RERUN_WINDOW_DAYS: int = int(os.getenv("AI_TRIAGE_RERUN_WINDOW_DAYS", "7"))
    # ===== 第二段 agent 复核 =====
    # 批量粗筛后，对命中候选起一个带工具的 agent 复核（查知识库/issue 详情/本地代码）
    AI_TRIAGE_AGENT_REVIEW: bool = os.getenv("AI_TRIAGE_AGENT_REVIEW", "true").lower() in ("1", "true", "yes")
    # 单条规则一轮复核的候选上限（超出部分保留粗筛结论不复核）
    AI_TRIAGE_AGENT_MAX_CANDIDATES: int = int(os.getenv("AI_TRIAGE_AGENT_MAX_CANDIDATES", "20"))
    # 复核 agent 的最大交互轮数
    AI_TRIAGE_AGENT_MAX_TURNS: int = int(os.getenv("AI_TRIAGE_AGENT_MAX_TURNS", "12"))

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