"""NPU 机型 profile 与 docker run 命令生成器

机型差异（设备数/镜像 tag 后缀/特有设备与挂载）依据 vllm-ascend 官方文档
installation.md / quick_start.md 整理，内置 a2 / a3 / 310p / other 四种
（a5/950dt 后续按需在此追加一个定义即可）。

build_docker_run() 生成完整 docker run 命令，提交前可在前端预览。
"""
import re
import shlex
from typing import Dict, List, Optional

from app.config import Config

# 所有机型必须挂载的基础设备与目录（官方安装文档统一清单）
BASE_DEVICES = ["/dev/davinci_manager", "/dev/devmm_svm", "/dev/hisi_hdc"]
BASE_MOUNTS = [
    "/usr/local/dcmi",
    "/usr/local/bin/npu-smi",
    "/usr/local/Ascend/driver/lib64/",
    "/usr/local/Ascend/driver/version.info",
    "/etc/ascend_install.info",
]
# host 网络（多机/RDMA）场景额外挂载
HOST_NET_MOUNTS = ["/usr/local/Ascend/driver/tools/hccn_tool"]

MACHINE_PROFILES: Dict[str, dict] = {
    "a2": {
        "label": "Atlas A2",
        "npu_count": 8,
        "image_suffix": "",
        "shm_size": "1g",
        "extra_devices": [],
        "extra_mounts": [],
        "notes": "8 卡（davinci0-7）",
    },
    "a3": {
        "label": "Atlas A3",
        "npu_count": 16,
        "image_suffix": "-a3",
        "shm_size": "1g",
        "extra_devices": [],
        "extra_mounts": [],
        "min_npus": 2,  # 官方要求 A3 至少 2 卡协同工作
        "notes": "16 卡（davinci0-15），最少 2 卡",
    },
    "310p": {
        "label": "Atlas 300I DUO",
        "npu_count": 2,
        "image_suffix": "-310p",
        "shm_size": "10g",
        "extra_devices": [],
        "extra_mounts": [],
        "notes": "仅支持 float16（--dtype float16）",
    },
    "other": {
        "label": "自定义机型",
        "npu_count": None,
        "image_suffix": "",
        "shm_size": "1g",
        "extra_devices": [],
        "extra_mounts": [],
        "notes": "设备与挂载全手动",
    },
}


def get_profile(machine_type: str) -> dict:
    profile = MACHINE_PROFILES.get(machine_type or "other")
    if profile is None:
        profile = MACHINE_PROFILES["other"]
    return profile


def default_image(machine_type: str) -> str:
    """机型默认镜像：repo:version[-机型后缀]"""
    suffix = get_profile(machine_type).get("image_suffix", "")
    return f"{Config.NPU_IMAGE_REPO}:{Config.NPU_IMAGE_VERSION}{suffix}"


def profile_options() -> List[dict]:
    """前端机型下拉选项"""
    return [
        {"value": mt, "label": p["label"], "npu_count": p["npu_count"],
         "notes": p["notes"], "default_image": default_image(mt)}
        for mt, p in MACHINE_PROFILES.items()
    ]


def _quote_mount(m: str) -> str:
    host, _, container = m.partition(":")
    if not container:
        host, container = m, m
    return f"-v {shlex.quote(host)}:{shlex.quote(container)}"


def build_docker_run(machine_type: str, spec: dict) -> str:
    """生成完整 docker run 命令。

    spec 字段：
    - mode: 'persistent' / 'oneshot'
    - image: 镜像名
    - device_ids: NPU 卡索引列表（如 [0,1]），None = 全部卡
    - extra_devices: 额外 --device 路径（other 机型手动指定）
    - mounts: 挂载列表，"host:container" 或 "host"（同路径）
    - env: 环境变量 dict
    - network: 'host' / 'bridge'
    - ports: "host:container" 列表（bridge 时）
    - shm_size: 如 '1g'（空 = 机型默认）
    - container_name / name: 容器名（必填）
    - command: 容器内执行命令；persistent 且为空时用 sleep infinity 常驻
    """
    profile = get_profile(machine_type)
    image = spec.get("image") or default_image(machine_type)
    name = spec.get("container_name") or spec.get("name") or ""
    if not name:
        raise ValueError("容器名不能为空")
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$", name):
        raise ValueError(f"容器名不合法: {name}")

    mode = spec.get("mode") or "oneshot"
    network = spec.get("network") or "host"
    persistent = mode == "persistent"

    parts: List[str] = ["docker run"]
    parts.append("-d" if persistent else "--rm")
    parts += ["--name", shlex.quote(name)]

    shm = spec.get("shm_size") or profile.get("shm_size") or "1g"
    parts += ["--shm-size", shm]

    if network == "host":
        parts.append("--net=host")
    else:
        for p in spec.get("ports") or []:
            parts += ["-p", shlex.quote(p)]

    # NPU 设备：device_ids 为 None 表示全部卡；否则按索引挂 davinciN
    npu_ids = spec.get("device_ids")
    total = profile.get("npu_count")
    if npu_ids is None and total:
        npu_ids = list(range(total))
    npu_ids = [int(i) for i in (npu_ids or [])]
    for i in npu_ids:
        parts += ["--device", f"/dev/davinci{i}"]
    for d in BASE_DEVICES + (profile.get("extra_devices") or []) + (spec.get("extra_devices") or []):
        parts += ["--device", d]

    # 选卡子集时注入 ASCEND_RT_VISIBLE_DEVICES（容器内可见 NPU ID 与 TP 映射一致）
    env = dict(spec.get("env") or {})
    if total and npu_ids and len(npu_ids) < total:
        env.setdefault("ASCEND_RT_VISIBLE_DEVICES", ",".join(str(i) for i in npu_ids))
    for k, v in env.items():
        parts += ["-e", shlex.quote(f"{k}={v}")]

    # 挂载：基础集 + 机型特有 + host 网络场景 + 用户自定义
    mounts = list(BASE_MOUNTS) + list(profile.get("extra_mounts") or [])
    if network == "host":
        mounts += HOST_NET_MOUNTS
    mounts += list(spec.get("mounts") or [])
    for m in mounts:
        parts.append(_quote_mount(m))

    parts.append(shlex.quote(image))

    command = (spec.get("command") or "").strip()
    if not command:
        command = "sleep infinity" if persistent else "echo 'no command' && exit 0"
    parts += ["bash", "-c", shlex.quote(command)]

    return " ".join(parts)
