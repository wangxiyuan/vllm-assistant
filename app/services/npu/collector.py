"""NPU 机器巡检采集

单条 SSH 命令一次性采集：npu-smi 信息（每卡利用率/显存/温度/功耗）、
系统指标（CPU/内存/磁盘）、模型权重目录、docker 镜像列表，减少往返。

巡检结果更新 NpuMachine 最新状态并（可选）写 NpuMachineMetric 历史，
同时增量同步 NpuImage / NpuModelDir 扫描缓存。
"""
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.database import SessionLocal
from app.models import NpuImage, NpuMachine, NpuMachineMetric, NpuModelDir
from app.config import Config
from app.services.npu import ssh

logger = logging.getLogger(__name__)


def _shell_path(p: Optional[str]) -> str:
    """远程 shell 路径处理：~/ 前缀改为 $HOME/ 以便在双引号内正确展开"""
    if not p:
        return ""
    if p.startswith("~/"):
        return "$HOME/" + p[2:]
    return p


def _build_inspect_command(model_root: str) -> str:
    model_root_sh = _shell_path(model_root)
    model_scan = ""
    if model_root_sh:
        # 两层扫描：root/<模型>/ 与 root/<org>/<模型>/（ModelScope/HuggingFace hub 布局）
        model_scan = (
            f'if [ -d "{model_root_sh}" ]; then '
            f'for d in "{model_root_sh}"/*/ "{model_root_sh}"/*/*/; do '
            f'if [ -f "$d/config.json" ] || ls "$d"*.safetensors* >/dev/null 2>&1 '
            f'|| ls "$d"pytorch_model*.bin >/dev/null 2>&1; then echo "${{d%/}}"; fi; '
            f"done; fi"
        )
    return (
        "npu-smi info 2>&1; "
        "echo '---SYS---'; "
        "top -bn2 -d 0.3 2>/dev/null | grep -i 'cpu(s)' | tail -1; "
        "free -m | grep Mem:; "
        "df -P / | tail -1; "
        "echo '---MODELS---'; "
        f"{model_scan}; "
        "echo '---IMAGES---'; "
        "docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null"
    )


_RE_NPU_ROW = re.compile(
    r"^\|\s*(\d+)\s+([A-Za-z0-9._-]+)\s*\|\s*(OK|Warning|Error|\S+)\s*\|"
    r"\s*([\d.]+|-)\s+(-?\d+|-)\s+(\d+|-)")
# 芯片明细行：| Chip Phy-ID | 总线地址(含 : . ) | AICore% 及若干 "used / total" 对，
# 显存(HBM)取行内最后一组 used/total（新版 npu-smi 中 Hugepages 在其前面）
_RE_CHIP_ROW = re.compile(
    r"^\|\s*\d+\s+\d+\s*\|\s*[\w:.]+\s*\|\s*(\d+)\s+(.*)$")
_RE_USAGE_PAIR = re.compile(r"(\d+)\s*/\s*(\d+)")
_RE_VERSION = re.compile(r"npu-smi\s+([\d.]+[^\s|]*)\s+.*Version:\s*([\d.]+[^\s|]*)")
_RE_CPU = re.compile(r"([\d.]+)\s*id")
_RE_MEM = re.compile(r"Mem:\s+(\d+)\s+(\d+)")


def _parse_npu_smi(text: str) -> Dict[str, Any]:
    """解析 npu-smi info 文本输出（表格格式随版本略有差异，逐行宽容匹配）"""
    cards: List[dict] = []
    version = ""
    for line in text.splitlines():
        m = _RE_VERSION.search(line)
        if m and not version:
            version = m.group(2)
            continue
        m = _RE_NPU_ROW.match(line)
        if m:
            cards.append({
                "index": int(m.group(1)),
                "chip": m.group(2),
                "health": m.group(3),
                "power": float(m.group(4)) if m.group(4) != "-" else None,
                "temperature": int(m.group(5)) if m.group(5) != "-" else None,
            })
            continue
        m = _RE_CHIP_ROW.match(line)
        if m and cards:
            cards[-1]["aicore"] = int(m.group(1))
            pairs = _RE_USAGE_PAIR.findall(m.group(2))
            if pairs:
                cards[-1]["mem_used"] = int(pairs[-1][0])
                cards[-1]["mem_total"] = int(pairs[-1][1])
    return {"version": version, "cards": cards}


def _parse_sys_section(lines: List[str]) -> Dict[str, Optional[float]]:
    """解析 ---SYS--- 段：CPU / 内存 / 磁盘 利用率"""
    result = {"cpu": None, "mem": None, "disk": None}
    for line in lines:
        m = _RE_CPU.search(line)
        if m:
            try:
                result["cpu"] = round(100.0 - float(m.group(1)), 1)
                continue
            except ValueError:
                pass
        m = _RE_MEM.search(line)
        if m and result["mem"] is None:
            total, used = int(m.group(1)), int(m.group(2))
            if total > 0:
                result["mem"] = round(used * 100.0 / total, 1)
                continue
        m = re.search(r"(\d+)%\s+/", line)
        if m and result["disk"] is None:
            result["disk"] = float(m.group(1))
    return result


def _split_sections(out: str) -> Dict[str, List[str]]:
    """按 ---MARK--- 分隔符切分输出段"""
    sections: Dict[str, List[str]] = {"main": [], "MODELS": [], "IMAGES": []}
    current = "main"
    for line in out.splitlines():
        m = re.match(r"^---(\w+)---\s*$", line.strip())
        if m:
            current = m.group(1)
            sections.setdefault(current, [])
            continue
        sections[current].append(line)
    return sections


def collect_machine(machine: dict, model_root: str = "") -> Dict[str, Any]:
    """执行一次采集并解析（纯采集，不落库），machine 为 to_ssh_params() 结果"""
    cmd = _build_inspect_command(model_root)
    exit_code, out, err = ssh.run_command(machine, cmd, timeout=120)
    if exit_code != 0 and not out:
        raise RuntimeError(f"巡检命令失败: {err.strip()[:300]}")

    sections = _split_sections(out)
    npu = _parse_npu_smi("\n".join(sections["main"]))
    sys_metrics = _parse_sys_section(sections["SYS"])
    models = [l.strip() for l in sections["MODELS"] if l.strip()]
    images = [l.strip() for l in sections["IMAGES"] if l.strip()]

    cards = npu["cards"]
    return {
        "npu_count": len(cards),
        "npu_chip": cards[0]["chip"] if cards else None,
        "driver_version": npu["version"] or None,
        "cards": cards,
        "npu_util": [c.get("aicore") for c in cards],
        "npu_mem_used": [c.get("mem_used") for c in cards],
        "npu_mem_total": [c.get("mem_total") for c in cards],
        "temperature": [c.get("temperature") for c in cards],
        "power": [c.get("power") for c in cards],
        "cpu": sys_metrics["cpu"],
        "mem": sys_metrics["mem"],
        "disk": sys_metrics["disk"],
        "models": models,
        "images": images,
        "health": [c.get("health") for c in cards],
    }


def _sync_model_dirs(db, machine_id: int, scanned: List[str]) -> None:
    """模型目录扫描增量同步（manual 来源的记录不受影响）"""
    scanned_set = set(scanned)
    existing = db.query(NpuModelDir).filter(
        NpuModelDir.machine_id == machine_id, NpuModelDir.source == "scan").all()
    existing_paths = {e.path for e in existing}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for p in scanned_set - existing_paths:
        db.add(NpuModelDir(machine_id=machine_id, path=p, source="scan"))
    for e in existing:
        if e.path not in scanned_set:
            db.delete(e)


def _sync_images(db, machine_id: int, scanned: List[str]) -> None:
    """镜像扫描增量同步（manual 来源的记录不受影响）"""
    scanned_set = set(scanned)
    existing = db.query(NpuImage).filter(
        NpuImage.machine_id == machine_id, NpuImage.source == "scan").all()
    existing_names = {e.full_name for e in existing}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for name in scanned_set - existing_names:
        db.add(NpuImage(machine_id=machine_id, full_name=name, source="scan", scanned_at=now))
    for e in existing:
        if e.full_name not in scanned_set:
            db.delete(e)


def inspect_machine(machine_id: int) -> Dict[str, Any]:
    """巡检一台机器并落库（更新最新状态 + 历史指标 + 扫描缓存）

    在巡检线程池中执行；返回巡检结果摘要。不持有 DB session 跨 SSH 操作。
    """
    db = SessionLocal()
    try:
        machine = db.query(NpuMachine).filter(NpuMachine.id == machine_id).first()
        if machine is None:
            return {"machine_id": machine_id, "ok": False, "message": "machine not found"}
        ssh_params = machine.to_ssh_params()
        model_root = machine.model_root or ""
        machine_name = machine.name
    finally:
        db.close()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        result = collect_machine(ssh_params, model_root=model_root)
    except Exception as e:
        db = SessionLocal()
        try:
            machine = db.query(NpuMachine).filter(NpuMachine.id == machine_id).first()
            if machine:
                machine.status = "offline"
                machine.status_message = str(e)[:500]
                machine.last_check_at = now
                db.commit()
        finally:
            db.close()
        logger.warning(f"NPU inspect failed for {machine_name}: {e}")
        return {"machine_id": machine_id, "ok": False, "message": str(e)[:300]}

    db = SessionLocal()
    try:
        machine = db.query(NpuMachine).filter(NpuMachine.id == machine_id).first()
        if machine is None:
            return {"machine_id": machine_id, "ok": False, "message": "machine not found"}
        machine.status = "online"
        machine.status_message = None
        machine.last_check_at = now
        machine.npu_count = result["npu_count"]
        machine.npu_chip = result["npu_chip"]
        machine.driver_version = result["driver_version"]

        if Config.NPU_METRICS_ENABLED:
            db.add(NpuMachineMetric(
                machine_id=machine_id,
                ts=now,
                npu_util=json.dumps(result["npu_util"]),
                npu_mem_used=json.dumps(result["npu_mem_used"]),
                npu_mem_total=json.dumps(result["npu_mem_total"]),
                temperature=json.dumps(result["temperature"]),
                power=json.dumps(result["power"]),
                cpu=result["cpu"],
                mem=result["mem"],
                disk=result["disk"],
            ))
        _sync_model_dirs(db, machine_id, result["models"])
        _sync_images(db, machine_id, result["images"])
        db.commit()
    finally:
        db.close()

    logger.info(f"NPU inspect ok: {machine_name} ({result['npu_count']} NPUs)")
    return {"machine_id": machine_id, "ok": True, "npu_count": result["npu_count"],
            "cpu": result["cpu"], "mem": result["mem"]}


def test_machine(machine_id: int) -> Dict[str, Any]:
    """纳管连通性测试：SSH 连接 + npu-smi 探测，结果落库 machine 字段"""
    db = SessionLocal()
    try:
        machine = db.query(NpuMachine).filter(NpuMachine.id == machine_id).first()
        if machine is None:
            return {"ok": False, "message": "machine not found"}
        ssh_params = machine.to_ssh_params()
        machine_name = machine.name
    finally:
        db.close()

    ok, message = ssh.test_connection(ssh_params)
    if not ok:
        db = SessionLocal()
        try:
            m = db.query(NpuMachine).filter(NpuMachine.id == machine_id).first()
            if m:
                m.status = "offline"
                m.status_message = message
                db.commit()
        finally:
            db.close()
        return {"ok": False, "message": message}

    try:
        result = collect_machine(ssh_params)
    except Exception as e:
        return {"ok": True, "message": f"SSH 连通，但采集失败: {e}", "npu_count": None}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db = SessionLocal()
    try:
        m = db.query(NpuMachine).filter(NpuMachine.id == machine_id).first()
        if m:
            m.status = "online"
            m.status_message = None
            m.last_check_at = now
            m.npu_count = result["npu_count"]
            m.npu_chip = result["npu_chip"]
            m.driver_version = result["driver_version"]
            db.commit()
    finally:
        db.close()

    return {
        "ok": True,
        "message": f"连接成功：{result['npu_count']} 卡 {result['npu_chip'] or ''}".strip(),
        "npu_count": result["npu_count"],
        "npu_chip": result["npu_chip"],
        "driver_version": result["driver_version"],
        "cards": result["cards"],
    }
