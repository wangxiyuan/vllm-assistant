"""
AI Assistant - OpenAI API 集成
提供 Review 意见生成、PR 影响范围分析等功能
"""
import json
import logging
import re
from typing import List, Dict, Any, Optional

from app.config import Config
from app.services.llm import LLMClient

logger = logging.getLogger(__name__)


class AIAssistant:
    """AI 助手，基于 OpenAI API 提供智能建议"""

    def __init__(self):
        self.llm = LLMClient()
        self.model = Config.OPENAI_MODEL

    def generate_review(
        self, pr_title: str, pr_diff: str, pr_number: int
    ) -> str:
        """
        基于PR diff生成 markdown 格式的 review 意见

        Args:
            pr_title: PR标题
            pr_diff: PR的diff内容
            pr_number: PR编号

        Returns:
            markdown 格式的 review 字符串
        """
        prompt = f"""你是一位资深贡献者，正在 review 一个 PR。

PR #{pr_number}: {pr_title}

PR Diff（超出 8000 字符的部分已截断，仅展示前 8000 字符）：
```diff
{pr_diff[:8000]}
```

请用中文写一份 markdown 格式的 review 意见。包含以下部分（用 markdown 标题分隔），每个部分用无序列表列出问题：

1. **总体评价** — 一句话总体评价
2. **代码质量** — 列出代码质量问题，每条注明严重程度（critical/important/minor）
3. **性能** — 列出性能相关问题，每条注明严重程度
4. **测试** — 列出测试相关问题，每条注明严重程度
5. **文档** — 列出文档相关问题，每条注明严重程度

格式示例：
### 总体评价
这个 PR 整体质量不错，但有一些关键问题需要解决。

### 代码质量
- **[critical]** 问题标题：详细说明
- **[important]** 问题标题：详细说明

### 性能
- **[important]** 问题标题：详细说明

如果某个方面没有问题，写"无"即可。

输出纯 markdown，不要用代码块包裹整个内容。"""

        try:
            content = self.llm.chat_sync(prompt, max_tokens=4096, temperature=0.7)
        except Exception as e:
            return f"**Review 生成失败**：{e}"

        if content and content.strip():
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:markdown)?\n?", "", content)
                content = re.sub(r"\n?```$", "", content)
            return content.strip()
        return "*暂无 Review 内容*"

    def analyze_impact(self, changed_files: List[str]) -> Dict[str, Any]:
        """
        分析PR影响范围

        Args:
            changed_files: 变更的文件列表

        Returns:
            {
                "affected_modules": [...],
                "potential_breaking_changes": bool,
                "test_requirements": [...],
                "cross_area_impact": [...],
            }
        """
        prompt = f"""Analyze the impact of these file changes:

Changed files:
{json.dumps(changed_files, indent=2)}

Return JSON with:
1. affected_modules: List of module names that may be affected
2. potential_breaking_changes: Boolean indicating if breaking changes are likely
3. test_requirements: List of test files that may need updates
4. cross_area_impact: List of areas that may be affected

Consider common project architecture:
- Core engine (scheduler, cache, distributed)
- Model implementation (attention, MoE, quantization)
- API/entrypoints
- Hardware integration (GPU, CPU, NPU, TPU)

Return valid JSON only."""

        try:
            content = self.llm.chat_sync(prompt, max_tokens=2048, temperature=0.5)
        except Exception as e:
            return {"error": str(e)}

        parsed = self.llm.safe_json(content, None)
        if parsed is not None:
            return parsed
        return {"error": "Failed to parse response", "raw_response": content}

    def suggest_labels(self, issue_title: str, issue_body: str) -> List[str]:
        """
        根据issue内容推荐标签和领域

        Args:
            issue_title: Issue标题
            issue_body: Issue正文

        Returns:
            推荐的标签列表
        """
        prompt = f"""Based on this issue, suggest appropriate labels and area.

Issue Title: {issue_title}
Issue Body: {issue_body[:2000]}

Label categories:
- Type: bug, feature, enhancement, documentation
- Area: engine, model, entrypoints, kernels, hardware, config, multimodal, compilation, lora, docs, ci
- Status: good first issue, help wanted, priority: high

Return JSON with:
1. labels: List of suggested labels
2. area: Suggested area (engine/model/entrypoints/etc.)
3. reasoning: Brief explanation

Return valid JSON only."""

        try:
            content = self.llm.chat_sync(prompt, max_tokens=1024, temperature=0.5)
        except Exception as e:
            logger.warning(f"suggest_labels failed: {e}")
            return []

        parsed = self.llm.safe_json(content, None)
        if isinstance(parsed, dict):
            return parsed.get("labels", []) or []
        return []

    def summarize(self, title: str, body: str, item_type: str) -> str:
        """为 issue 或 PR 生成 markdown 格式的中文摘要

        返回 markdown 字符串，前端用 marked 渲染。仅本地展示，不做任何 GitHub 写操作。

        Args:
            title: 标题
            body: 正文（Markdown）
            item_type: 'issue' or 'pr'

        Returns:
            markdown 格式的摘要字符串
        """
        if not body:
            body = "(无正文)"
        kind = "Issue" if item_type == "issue" else "Pull Request"

        if item_type == "issue":
            prompt = f"""分析以下 Issue，用中文写一段 markdown 格式的摘要。

要求包含以下几部分（用 markdown 标题分隔）：
- **核心问题**：这个 issue 报告了什么问题或提出了什么需求（1-2句）
- **关键要点**：用无序列表列出 2-4 个最有价值的信息点（如复现条件、环境、错误信息等）
- **影响范围**：对用户/项目的影响程度和范围
- **注意事项**：如果不解决可能带来的风险，或处理时需要注意的点。如果无明显风险，写"暂无"

标题：{title}

正文：
{body[:4000]}

输出纯 markdown，不要用代码块包裹整个内容。"""
        else:
            prompt = f"""分析以下 Pull Request，用中文写一段 markdown 格式的摘要。

要求包含以下几部分（用 markdown 标题分隔）：
- **核心问题**：这个 PR 解决了什么问题或实现了什么功能（1-2句）
- **关键要点**：用无序列表列出 2-4 个关键技术实现要点
- **影响范围**：对项目的影响（性能提升幅度、功能变化、兼容性等）
- **注意事项**：潜在风险（边界条件未处理、性能回归风险、兼容性等）。如果无明显风险，写"暂无"

标题：{title}

正文：
{body[:4000]}

输出纯 markdown，不要用代码块包裹整个内容。"""

        try:
            content = self.llm.chat_sync(prompt, max_tokens=1024, temperature=0.3)
        except Exception as e:
            return f"**摘要生成失败**：{e}"

        if content and content.strip():
            # 清理可能多余的代码块包裹
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:markdown)?\n?", "", content)
                content = re.sub(r"\n?```$", "", content)
            return content.strip()
        return "*暂无摘要*"

    def translate(self, text: str, item_type: str) -> str:
        """将 Issue/PR 正文翻译为中文"""
        if not text:
            return ""

        prompt = f"""你是一个技术文档翻译专家。请将以下英文技术内容翻译成流畅的中文。

## 核心原则

1. **保留所有 Markdown 格式** — 标题（###）、列表（- / *）、代码块（```）、引用（>）、表格、粗体（**）、链接、图片等**完全保留原样**，不要添加或删除任何格式标记
2. **保留 GitHub 特有结构** — `<details><summary>` 折叠块、`### Section Title` 标题、环境信息表格等，原样保留标签和结构，只翻译其中的文本内容
3. **保留代码、变量名、路径、命令** — 代码片段、变量名、文件路径、GitHub 用户名、命令行参数、环境变量等**原样保留，不翻译**
4. **保留技术术语原文** — 以下术语**保持英文原文，不翻译**：
   - 模型架构：Attention、KV Cache、MoE、MLP、FFN、LayerNorm、RMSNorm、RoPE、GQA、MHA
   - 硬件：GPU、CUDA、kernel、Tensor Parallelism、Pipeline Parallelism、TP、PP
   - 量化：quantization、FP8、FP4、INT8、INT4、AWQ、GPTQ、SmoothQuant
   - 推理：throughput、latency、batch、prefill、decode、scheduler、block manager
   - 分布式：allreduce、allgather、NCCL、Ray、RPC、p2p
   - 工具：vLLM、PyTorch、Triton、FlashAttention、Transformer
   - 如果术语有公认中文译名且上下文需要，可保留英文并在括号内加中文注释，如 "KV Cache（键值缓存）"
5. **保留链接和图片** — Markdown 链接 `[text](url)` 和图片 `![alt](url)` 原样保留，不要修改
6. **保持原文段落结构** — 不要合并或拆分段落，保留空行分隔
7. **只输出翻译结果** — 不要加任何解释、前言、后记或额外说明
8. **中英文混合处理** — 如果原文已包含中文，只翻译英文部分，已有中文保持原样
9. **错误信息和日志** — 错误信息、堆栈跟踪、日志输出等代码相关内容**不翻译**，保持原样
10. **数字和单位** — 数字、百分比、单位（GB、MB、ms、s 等）保持原样

## 翻译风格

- 使用正式但不生硬的技术文档语言
- 句子要通顺，符合中文表达习惯
- 长句适当拆分，保持可读性
- 保持原文的语气（疑问、陈述、强调等）

原文（{'Issue' if item_type == 'issue' else 'PR'} 描述）：
{text}

翻译："""

        try:
            content = self.llm.chat_sync(prompt, max_tokens=65536, temperature=0.1)
            return content.strip() if content else text
        except Exception:
            logger.exception("translate failed")
            return text