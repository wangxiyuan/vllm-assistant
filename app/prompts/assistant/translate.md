将以下技术内容翻译成流畅的中文。只输出翻译结果，不要加任何解释或前言。

原文（{{ item_type }} 描述）：
{{ text }}

翻译：

## 翻译规则

**格式保留（原样不动，只翻译其中的文本）：**
- Markdown：标题、列表、代码块、引用、表格、粗体、链接、图片
- GitHub 特有结构：`<details><summary>` 折叠块、环境信息表格
- 代码、变量名、文件路径、命令、GitHub 用户名

**术语保留英文原文，不翻译：**
- 模型架构：Attention、KV Cache、MoE、MLP、FFN、LayerNorm、RoPE、GQA
- 硬件：GPU、CUDA、kernel、Tensor Parallelism、Pipeline Parallelism
- 量化：quantization、FP8、INT8、INT4、AWQ、GPTQ、SmoothQuant
- 推理：throughput、latency、batch、prefill、decode、scheduler
- 分布式：allreduce、allgather、NCCL、Ray、RPC
- 工具：vLLM、PyTorch、Triton、FlashAttention、Transformer
- 其他未被列出的技术术语同样保留英文。如术语有公认中文译名，可保留英文并在括号内加中文注释，如 "KV Cache（键值缓存）"

**其他：**
- 错误信息、堆栈跟踪、日志输出不翻译
- 数字、百分比、单位（GB、MB、ms、s）保持原样
- 原文已包含中文的部分保持原样，只翻译英文部分
- 保持原文段落结构，不要合并或拆分段落

## 翻译风格
正式但不生硬的技术文档语言，句子通顺，长句适当拆分。