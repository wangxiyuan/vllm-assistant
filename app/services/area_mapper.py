"""
CODEOWNERS 解析和领域映射模块

领域定义基于 vLLM 仓库的 .github/CODEOWNERS 文件结构，
覆盖 vLLM 的核心模块和功能区域。
"""
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class AreaMapper:
    """将文件路径映射到领域"""

    # vLLM 主要领域定义（基于 CODEOWNERS 文件的实际结构）
    AREA_DEFINITIONS = {
        "compilation": {
            "name": "编译优化",
            "description": "torch.compile、CUDA graph、IR",
            "paths": [
                "vllm/compilation/",
                "vllm/ir/",
            ],
        },
        "distributed": {
            "name": "分布式",
            "description": "分布式训练、KV transfer、Pipeline parallel",
            "paths": [
                "vllm/distributed/",
                "vllm/distributed/kv_transfer/",
            ],
        },
        "lora": {
            "name": "LoRA",
            "description": "LoRA 低秩适配",
            "paths": [
                "vllm/lora/",
            ],
        },
        "attention": {
            "name": "Attention",
            "description": "Attention 层实现（含 V1/V2、各后端）",
            "paths": [
                "vllm/model_executor/layers/attention/",
                "vllm/v1/attention/",
                "vllm/vllm_flash_attn/",
            ],
        },
        "moe": {
            "name": "MoE",
            "description": "Fused MoE 层",
            "paths": [
                "vllm/model_executor/layers/fused_moe/",
            ],
        },
        "quantization": {
            "name": "量化",
            "description": "量化层（GPTQ、AWQ、FP8 等）",
            "paths": [
                "vllm/model_executor/layers/quantization/",
            ],
        },
        "mamba": {
            "name": "Mamba/SSM",
            "description": "Mamba、状态空间模型",
            "paths": [
                "vllm/model_executor/layers/mamba/",
            ],
        },
        "model_loader": {
            "name": "模型加载",
            "description": "模型加载器、权重加载",
            "paths": [
                "vllm/model_executor/model_loader/",
            ],
        },
        "kernels": {
            "name": "Kernels",
            "description": "CUDA/Triton kernels",
            "paths": [
                "vllm/kernels/",
                "csrc/",
            ],
        },
        "multimodal": {
            "name": "多模态",
            "description": "多模态输入处理、渲染器",
            "paths": [
                "vllm/multimodal/",
                "vllm/inputs/",
                "vllm/renderers/",
            ],
        },
        "config": {
            "name": "配置",
            "description": "VllmConfig、参数解析",
            "paths": [
                "vllm/config/",
                "vllm/engine/arg_utils.py",
                "vllm/utils/argparse_utils.py",
            ],
        },
        "entrypoints": {
            "name": "入口点",
            "description": "API server、CLI、OpenAI/Anthropic/MCP 兼容层",
            "paths": [
                "vllm/entrypoints/",
                "vllm/api/",
            ],
        },
        "rust": {
            "name": "Rust 前端",
            "description": "Rust 前端、构建脚本",
            "paths": [
                "rust/",
                "build_rust.sh",
                "rust-toolchain.toml",
            ],
        },
        "sampling": {
            "name": "采样/参数",
            "description": "采样参数、pooling、tokenizers、reasoning、tool_parsers",
            "paths": [
                "vllm/sampling_params.py",
                "vllm/pooling_params.py",
                "vllm/tokenizers/",
                "vllm/reasoning/",
                "vllm/tool_parsers/",
                "vllm/parser/",
            ],
        },
        "v1_core": {
            "name": "V1 核心",
            "description": "V1 核心：调度、KV cache、spec decode、structured output",
            "paths": [
                "vllm/v1/core/",
                "vllm/v1/sample/",
                "vllm/v1/spec_decode/",
                "vllm/v1/structured_output/",
                "vllm/v1/kv_cache_interface.py",
                "vllm/v1/kv_offload/",
                "vllm/v1/simple_kv_offload/",
                "vllm/v1/engine/",
                "vllm/v1/executor/",
                "vllm/v1/worker/",
            ],
        },
        "ci": {
            "name": "CI/构建",
            "description": "CI 配置、Docker、构建工具",
            "paths": [
                ".buildkite/",
                "docker/",
                "pyproject.toml",
                "setup.py",
                "CMakeLists.txt",
                "cmake/",
            ],
        },
        "tests": {
            "name": "测试",
            "description": "测试用例",
            "paths": [
                "tests/",
            ],
        },
        "docs": {
            "name": "文档",
            "description": "文档、mkdocs 配置",
            "paths": [
                "docs/",
                "*.md",
                "README.md",
                ".readthedocs.yaml",
                "mkdocs.yaml",
                ".markdownlint.yaml",
                ".pre-commit-config.yaml",
            ],
        },
        "cpu": {
            "name": "CPU",
            "description": "CPU 后端",
            "paths": [
                "vllm/v1/worker/cpu",
                "csrc/cpu/",
                "vllm/platforms/cpu.py",
                "cmake/cpu_extension.cmake",
                "docker/Dockerfile.cpu",
            ],
        },
        "gpu_hardware": {
            "name": "GPU/硬件",
            "description": "GPU worker、平台适配（含 ROCm、TPU、Intel GPU）",
            "paths": [
                "vllm/v1/worker/gpu/",
                "vllm/platforms/",
                "vllm/v1/worker/xpu",
                "vllm/platforms/xpu.py",
                "vllm/v1/worker/tpu",
                "vllm/platforms/tpu.py",
            ],
        },
        "engine": {
            "name": "Engine",
            "description": "老引擎（兼容层）",
            "paths": [
                "vllm/engine/",
                "vllm/scheduler/",
            ],
        },
        "model": {
            "name": "模型实现",
            "description": "具体模型实现（fallback：未被 CODEOWNERS 精确匹配的模型文件）",
            "paths": [
                "vllm/model_executor/",
                "vllm/model_executor/models/",
            ],
        },
    }

    def __init__(self):
        self.area_map: Dict[str, str] = {}  # path -> area_id
        self._load_codeowners()

    def _load_codeowners(self):
        """从 CODEOWNERS 文件加载领域映射"""
        try:
            from app.services.github_client import GitHubClient

            client = GitHubClient()
            codeowners_content = client.get_codeowners()

            if codeowners_content:
                self._parse_codeowners(codeowners_content)
            else:
                self._use_default_mapping()
        except Exception as e:
            logger.warning(f"Failed to load CODEOWNERS, falling back to defaults: {e}")
            self._use_default_mapping()

    def _parse_codeowners(self, content: str):
        """解析 CODEOWNERS 文件内容"""
        lines = content.strip().split("\n")

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # 匹配模式: pattern @owner1 @owner2
            match = re.match(r"^([^\s]+)\s+(.+)$", line)
            if match:
                pattern, _ = match.groups()

                # 确定领域
                area_id = self._identify_area(pattern)
                if area_id:
                    self.area_map[pattern] = area_id

        # 没有解析到任何映射则用默认
        if not self.area_map:
            self._use_default_mapping()

    def _identify_area(self, pattern: str) -> Optional[str]:
        """根据 CODEOWNERS 模式识别领域"""
        pattern_lower = pattern.lower()

        for area_id, definition in self.AREA_DEFINITIONS.items():
            for path in definition["paths"]:
                path_lower = path.lower()
                # 目录路径：检查 pattern 是否以该路径开头
                if path_lower.endswith("/"):
                    if pattern_lower.startswith(path_lower):
                        return area_id
                # 精确文件匹配
                elif path_lower.startswith("*."):
                    suffix = path_lower[1:]  # e.g. ".md" from "*.md"
                    if pattern_lower.endswith(suffix):
                        return area_id
                else:
                    if pattern_lower == path_lower or pattern_lower.endswith("/" + path_lower):
                        return area_id

        return None

    def _use_default_mapping(self):
        """使用默认映射（当无法获取 CODEOWNERS 时）"""
        for area_id, definition in self.AREA_DEFINITIONS.items():
            for path in definition["paths"]:
                self.area_map[path] = area_id

    def map_to_area(self, file_path: str) -> Optional[str]:
        """将文件路径映射到领域 ID

        策略：先匹配 CODEOWNERS 的精确模式，再匹配 AREA_DEFINITIONS 的路径前缀。
        遍历所有领域，返回最长匹配（最具体的领域）。
        """
        file_path_lower = file_path.lower()

        # 第一轮：检查 CODEOWNERS 模式（精确匹配优先）
        best_match = None
        best_match_len = 0
        for pattern, area_id in self.area_map.items():
            if self._match_pattern(file_path_lower, pattern.lower()):
                # 选择最长匹配的模式（更具体）
                if len(pattern) > best_match_len:
                    best_match = area_id
                    best_match_len = len(pattern)
        if best_match:
            return best_match

        # 第二轮：用 AREA_DEFINITIONS 的路径前缀匹配
        # 选择最长匹配前缀（更具体的领域优先）
        best_match = None
        best_match_len = 0
        for area_id, definition in self.AREA_DEFINITIONS.items():
            for path in definition["paths"]:
                path_lower = path.lower()
                if file_path_lower.startswith(path_lower):
                    if len(path_lower) > best_match_len:
                        best_match = area_id
                        best_match_len = len(path_lower)

        return best_match

    def _match_pattern(self, file_path: str, pattern: str) -> bool:
        """匹配文件路径和 CODEOWNERS 模式

        支持：
        - 目录前缀：/vllm/config/ 匹配 /vllm/config/xxx
        - 通配符：/*.py 匹配任何 .py
        - ** 递归通配：/tests/**/*rocm* 匹配任意层级
        - 精确匹配
        """
        # 处理 ** 递归通配
        if "**" in pattern:
            # 转成正则：** -> .*, * -> [^/]*
            regex_pattern = re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
            return bool(re.match("^" + regex_pattern + "$", file_path))

        # 以 /* 结尾：匹配目录下所有文件
        if pattern.endswith("/*"):
            prefix = pattern[:-2]
            return file_path.startswith(prefix)
        # 以 / 结尾：匹配目录
        elif pattern.endswith("/"):
            return file_path.startswith(pattern)
        # 精确匹配
        else:
            return file_path == pattern

    def get_area_info(self, area_id: str) -> Optional[Dict]:
        """获取领域信息"""
        if area_id in self.AREA_DEFINITIONS:
            return self.AREA_DEFINITIONS[area_id].copy()
        return None

    def get_all_areas(self) -> List[Dict]:
        """获取所有领域信息"""
        areas = []
        for area_id, definition in self.AREA_DEFINITIONS.items():
            info = definition.copy()
            info["id"] = area_id
            areas.append(info)
        return areas

    def classify_issue_by_labels(self, labels: List[str]) -> Optional[str]:
        """根据标签分类 issue"""
        label_map = {
            "area/engine": "engine",
            "area/model": "model",
            "area/entrypoints": "entrypoints",
            "area/kernels": "kernels",
            "area/hardware": "gpu_hardware",
            "area/config": "config",
            "area/multimodal": "multimodal",
            "area/compilation": "compilation",
            "area/lora": "lora",
            "area/docs": "docs",
            "area/ci": "ci",
            "area/attention": "attention",
            "area/quantization": "quantization",
            "area/distributed": "distributed",
            "area/performance": "v1_core",
            "area/moe": "moe",
            "area/testing": "tests",
        }

        for label in labels:
            if label in label_map:
                return label_map[label]

        return None
