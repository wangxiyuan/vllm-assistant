"""
报告生成进度存储（内存，单进程适用）

后台线程生成报告时把阶段/工具进度写入这里，前端通过
GET /api/intelligence/reports/{id}/progress 拉取。

生产环境为单进程 uvicorn，内存表安全。若未来多进程可换 DB/Redis。
"""
import logging
import threading
from time import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_progress: Dict[int, dict] = {}

# 阶段显示名
STAGE_LABELS = {
    "search": "搜索情报",
    "detail": "深入分析",
    "report": "撰写报告",
}

# 阶段进度权重（用于百分比）
STAGE_WEIGHTS = {
    "search": 0.3,
    "detail": 0.5,
    "report": 0.2,
}

# 阶段名 → 前面的累计权重（当前阶段进行中的起点百分比）
STAGE_PREFIX = {
    "search": 0.0,
    "detail": 0.3,
    "report": 0.8,
}
# 每记录 k 个工具，在当前阶段内推进一点（避免 100% 冲刺感太强）
TOOLS_PER_BUMP = 5
STAGE_INNER = {
    "search": 0.25,
    "detail": 0.45,
    "report": 0.19,
}


def init_report_progress(
    report_id: int,
    stages: Optional[list] = None,
    title: str = "",
) -> None:
    """初始化一条进度记录。"""
    with _lock:
        _progress[report_id] = {
            "report_id": report_id,
            "title": title,
            "stage": "search",           # 当前阶段
            "stage_index": 0,
            "total_stages": len(stages) if stages else 3,
            "tools": [],                 # 当前阶段已调用工具名（去重）
            "tool_count": 0,
            "tool_bump_target": 8,
            "progress": 0.02,            # 0~1
            "status": "running",
            "updated_at": time(),
            "stages": stages or [STAGE_LABELS.get(s, s) for s in ("search", "detail", "report")],
        }


def update_stage(
    report_id: int,
    stage: str,
    stage_index: int,
) -> None:
    """切换阶段，重置该阶段工具统计。"""
    with _lock:
        rec = _progress.get(report_id)
        if not rec:
            return
        rec["stage"] = stage
        rec["stage_index"] = stage_index
        rec["tools"] = []
        rec["tool_count"] = 0
        rec["tool_bump_target"] = 5 if stage == "search" else (8 if stage == "detail" else 2)
        rec["updated_at"] = time()
        _recalc(report_id)


def add_tool(
    report_id: int,
    tool_name: str,
) -> None:
    """记录当前阶段调用了一个工具。"""
    with _lock:
        rec = _progress.get(report_id)
        if not rec:
            return
        if tool_name and tool_name not in rec["tools"]:
            rec["tools"].append(tool_name)
            rec["tool_count"] += 1
            rec["updated_at"] = time()
            _recalc(report_id)


def _recalc(report_id: int) -> None:
    rec = _progress.get(report_id)
    if not rec:
        return
    stage = rec["stage"]
    prefix = STAGE_PREFIX.get(stage, 0.0)
    inner_total = STAGE_INNER.get(stage, 0.1)
    # 当前阶段内按已用工具数线性推进（不跑到阶段边界，留点余量）
    inner = min(rec["tool_count"] / max(rec.get("tool_bump_target") or 1, 1), 1.0)
    rec["progress"] = round(min(prefix + inner * inner_total, 0.99), 3)


def complete_report(report_id: int) -> None:
    """标记进度完成。"""
    with _lock:
        rec = _progress.get(report_id)
        if not rec:
            return
        rec["status"] = "completed"
        rec["progress"] = 1.0
        rec["updated_at"] = time()


def get_report_progress(report_id: Optional[int]) -> Optional[dict]:
    if report_id is None:
        return None
    with _lock:
        return dict(_progress.get(report_id) or {})


def clear_report_progress(report_id: int) -> None:
    with _lock:
        _progress.pop(report_id, None)