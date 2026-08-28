# vLLM Assistant 模型 YAML 规范

本文档定义如何在 `vllm-assistant` 中编写一个**模型拆解（build building blocks）**的 YAML。
YAML 是本系统「模型拆解 / 搭积木」功能的**唯一数据源**：积木、组合、模型全部由用户编写的 YAML 定义，导入后由后端解析、校验、入库，前端据此渲染思维导图 / 结构树 / 流程图。

---

## 1. 设计理念：三层积木

一个深度学习模型（以 vLLM 文本大模型为例）可以拆成**三种粒度**的积木：

| kind | 含义 | 是否可独立部署 | 对应 | 例子 |
|------|------|--------------|------|------|
| **`atomic`** | 原子积木：不可再分的基础层/op | ❌ | 单个 vLLM `PluggableLayer`/`CustomOp`/`nn.Module` 类 | `VocabParallelEmbedding`、`RMSNorm`、`ColumnParallelLinear` |
| **`composite`** | 组合积木：若干子积木通过端口连接 | ❌ | 被入口模型**内部持有**、可复用的模块组合 | `Glm5NextDecoderLayer`、`Glm5NextMoE`、`Glm5NextModel` |
| **`assembly`** | 模型组装（入口）：vLLM 调用时的**第一层** | ✅ | registry 里可加载的顶层模型类 | `Glm5NextForConditionalGeneration`、`Glm5NextMTP`、`Glm5NextForCausalLM` |

> **判定规则**
> - `assembly` = vLLM 能直接实例化/加载的**第一层入口**（registry 注册的类）。
> - `composite` = 被入口（或其他 composite）**当作子模块持有**的组合结构。
> - `atomic` = 不可再分的单层/单 op。

---

## 2. 文件结构

一个 YAML 文件是一个**顶层列表**（`-` 开头），每一项是一个积木/模型定义。可以包含任意多个，顺序无强制要求（但被引用的块最终需能被解析）。

```yaml
# 可选的注释说明
- kind: atomic
  name: RMSNorm
  ...
- kind: composite
  name: Glm5NextDecoderLayer
  ...
- kind: assembly
  name: Glm5NextForCausalLM
  ...
```

> 中文注释、字段名均允许。字符串用单/双引号包裹（内含特殊字符如 `${}`、`[...]` 时建议用引号）。

---

## 3. 公共顶层字段（所有 kind 通用）

| 字段 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `kind` | ✅ | string | `atomic` / `composite` / `assembly` |
| `name` | ✅ | string | 全局唯一标识，推荐用 vLLM 类名 |
| `category` | 否 | string | 分类（`embedding`/`attention`/`mlp`/`moe`/`normalization`/`linear`/`activation`/`head`/`decoder_layer`/`mtp`/`multimodal`/`hybrid` 等） |
| `description` | 否 | string | 一句话说明 |
| `config` | 否 | object | **用户提供的模型 config**（见 §6），用于解析 `${config.xxx}` |
| `tags` | 否 | list[str] | 标签 |

---

## 4. `atomic` —— 原子积木

```yaml
- kind: atomic
  name: VocabParallelEmbedding
  category: embedding
  description: 沿词表维度并行的 Embedding。
  params_schema:            # JSON Schema，声明构造参数
    type: object
    required: [num_embeddings, embedding_dim]
    properties:
      num_embeddings:
        type: integer
        source: config.vocab_size        # 参数来源（运行时从哪个 config 字段读）
      embedding_dim:
        type: integer
        source: config.hidden_size
      padding_size:
        type: integer
        default: 64                        # 默认值
      disable_tp:
        type: boolean
        default: false
  ports:                    # 端口声明
    inputs:
      - { id: input_ids, type: tensor, shape: "[B, S]", dtype: int64, role: token_ids }
    outputs:
      - { id: hidden, type: tensor, shape: "[B, S, H]", dtype: float16, role: activation }
  vllm:                     # vLLM 代码映射（溯源）
    class: VocabParallelEmbedding
    base_class: PluggableLayer
    file: vllm/model_executor/layers/vocab_parallel_embedding.py
    weights:
      - { name: weight, shape: "[V_padded, H]", loader: weight_loader }
```

### 4.1 `params_schema`（JSON Schema 构造参数）

每个属性（property）可带：

| 字段 | 说明 |
|------|------|
| `type` | 类型：`integer`/`number`/`string`/`boolean`/`array`/`object` |
| `source` | 运行时从 `config.<字段>` 读取（用于前端从模型 config 还原具体值） |
| `default` | 默认值 |
| `nullable` | `true` 表示可为 null |
| `items` | `type: array` 时的元素类型 |
| `parallel_config` | 从并行配置读取（如 `use_sequence_parallel_moe`） |
| `condition` | 可选表达式，控制该参数是否生效 |
| `description` | 描述 |

### 4.2 `ports`（端口）

`inputs` / `outputs` 各为一个列表，每端口：

| 字段 | 说明 |
|------|------|
| `id` | 端口名 |
| `type` | `tensor` / `module` / 其他 |
| `shape` | 形状表达式，如 `"[B, S, H]"`；`B/S/H/V` 等符号由 config 求值 |
| `dtype` | 数据类型（`int64`/`float16`/`float32` 等） |
| `role` | 语义角色：`token_ids`/`activation`/`residual`/`distribution`/`router_logits` 等 |
| `optional` | `true` 表示可选端口 |
| `description` | 描述 |

### 4.3 `vllm`（代码映射）

| 字段 | 说明 |
|------|------|
| `class` | vLLM 类名 |
| `base_class` | 基类（`PluggableLayer`/`CustomOp`/`nn.Module`） |
| `file` | 源文件路径 |
| `op_name` | CustomOp 注册名（若有） |
| `weights` | 权重表：`[{name, shape, loader}]` |
| `nonzero_last_dim` | 激活层专用标记 |
| `ops` | 组合使用的 op 列表 |

---

## 5. `composite` —— 组合积木

```yaml
- kind: composite
  name: Glm5NextMLP
  category: ffn
  description: Dense MLP：gate_up → SwiGLU → down。
  params_schema:
    type: object
    properties:
      hidden_size:       { type: integer, source: config.hidden_size }
      intermediate_size: { type: integer, source: config.intermediate_size }
  children:                      # ← 子积木列表（关键）
    - { id: gate_up, block: MergedColumnParallelLinear,
        port_bind: { input_size: "${config.hidden_size}", output_sizes: "[${config.intermediate_size}, ${config.intermediate_size}]" } }
    - { id: act, block: SiluAndMulWithClamp, port_bind: { swiglu_limit: "${config.swiglu_limit}" },
        condition: "config.swiglu_limit is not None" }
    - { id: act_plain, block: SiluAndMul, condition: "config.swiglu_limit is None" }
    - { id: down, block: RowParallelLinear,
        port_bind: { input_size: "${config.intermediate_size}", output_size: "${config.hidden_size}" } }
  edges:                          # ← 端口连接
    - { from: {id: x}, to: {id: gate_up, port: x} }
    - { from: {id: gate_up, port: cats}, to: {id: act, port: x}, condition: "config.swiglu_limit is not None" }
    - { from: {id: act, port: y}, to: {id: down, port: x} }
    - { from: {id: down, port: y}, to: {id: y} }
  ports:
    inputs:  [{ id: x, type: tensor, shape: "[..., H]" }]
    outputs: [{ id: y, type: tensor, shape: "[..., H]" }]
  vllm:
    class: Glm5NextMLP
    file: vllm/models/glm5next/nvidia/model.py
```

### 5.1 `children`（子积木列表）

每项：

| 字段 | 说明 |
|------|------|
| `id` | 该子积木在组合内的唯一标识 |
| `block` | 引用的积木名（`atomic` 或 `composite`，即另一个 YAML 块的 `name`） |
| `port_bind` | 对该子积木参数的绑定/覆写（可用 `${...}` 模板） |
| `condition` | 可选表达式：满足才包含此子积木（用于同一组合内做分支，如 dense/MoE、条件开关） |
| `loop` | 可选：循环实例化（见 §5.4） |
| `note` | 备注 |

### 5.2 `edges`（端口连接）

每项：

| 字段 | 说明 |
|------|------|
| `from.id` | 起点：子积木 `id`，或本组合的输入端口 `id`，或 `from_segment` 配合 |
| `from.port` | 起点输出端口（可选） |
| `from_segment` | 若起点是合并投影的输出，标注取哪个 split 段名（配合顶层 `segments`） |
| `to.id` | 终点：子积木 `id`，或本组合的输出端口 `id` |
| `to.port` | 终点输入端口（可选） |
| `condition` | 可选：该连线仅满足条件时存在 |
| `note` | 备注 |

### 5.3 `segments`（可选，合并投影 split 说明）

当一个多列合并投影的输出被 `from_segment` 切分时，用 `segments` 说明各段偏移/大小：

```yaml
segments:
  - { name: q,   offset: 0,                       size: proj,      source: qkvbfga }
  - { name: k,   offset: proj,                    size: proj,      source: qkvbfga }
  - { name: v,   offset: 2*proj,                  size: proj,      source: qkvbfga }
  - { name: f_a, offset: 3*proj + num_heads,      size: head_dim,  source: qkvbfga }
```

### 5.4 `loop`（循环实例化）

用于描述重复结构（如 N 层 decoder）：

```yaml
- id: layers
  block: Glm5NextDecoderLayer
  loop:
    count: "${config.num_hidden_layers}"     # 循环次数（可引用 config）
    per_iter_bind:                            # 每轮给子积木的参数（可引用 loop_index）
      layer_idx: "${loop_index}"
```

| 字段 | 说明 |
|------|------|
| `count` | 循环次数，可为数字或 `${config.xxx}`（由模型 config 解析） |
| `per_iter_bind` | 每轮迭代注入子积木的参数；可用 `loop_index` 表示当前下标 |

---

## 6. `assembly` —— 模型组装（入口）

```yaml
- kind: assembly
  name: Glm5NextForCausalLM
  category: hybrid
  description: 完整因果语言模型（纯文本入口）。
  config:                    # ← 该入口模型的 config（用户提供，供 ${config.x} 解析）
    num_hidden_layers: 45
    hidden_size: 4096
    vocab_size: 154880
    tie_word_embeddings: false
    # ...（该模型在 config.json 里的关键字段）
  steps:                     # ← 顶层组件序列
    - { id: decoder, block: Glm5NextModel, as: model }
    - { id: lm_head, block: ParallelLMHead, as: lm_head,
        port_bind: { vocab_size: "${config.vocab_size}", hidden_size: "${config.hidden_size}" },
        condition: "not config.tie_word_embeddings" }
    - { id: logits_processor, block: LogitsProcessor, as: logits_processor, port_bind: { scale: 1.0 } }
  edges:                     # ← 顶层数据流
    - { from: {id: input_ids}, to: {id: decoder, port: input_ids} }
    - { from: {id: decoder, port: hidden}, to: {id: lm_head, port: hidden} }
    - { from: {id: lm_head, port: logits}, to: {id: logits_processor, port: hidden} }
    - { from: {id: logits_processor, port: logits}, to: {id: out} }
  ports:
    inputs:  [{ id: input_ids, type: tensor, shape: "[B, S]", dtype: int64, role: token_ids }]
    outputs: [{ id: logits,    type: tensor, shape: "[B, S, V]", dtype: float32, role: distribution }]
```

### 6.1 `config`（用户提供，关键）

- 每个**入口 assembly 应提供** `config`，即该模型 `config.json` 里的关键超参数（扁平化，键与 `${config.xxx}` 引用对应）。
- 前端 / 后端据此把 `"${config.num_hidden_layers}"` 解析成具体数值（如 `45`）用于展示。
- 被 `assembly` 持有的 `composite` / `atomic` **无需重复提供 config**；求值时按"被引用块自带 config → 入口 config"依次查找。
- `config` 是**用户的责任**，不内置任何模型数据。

### 6.2 `steps`（顶层组件）

与 `composite.children` 结构一致（`id`/`block`/`as`/`port_bind`/`condition`/`loop`/`note`）。`as` 表示该组件实例在模型里的属性名。

---

## 7. 表达式模板 `${...}`

`port_bind`、`loop.count`、`per_iter_bind`、`condition` 中可用 `${expr}` 引用 config 或做算术：

| 写法 | 示例 | 结果（假设 config.hidden_size=4096, n=288） |
|------|------|------|
| 引用 config | `${config.hidden_size}` | `4096` |
| 算术 | `${config.moe_intermediate_size} * ${config.n_shared_experts}` | `2048 * 1 = 2048` |
| 数组 | `"[${config.intermediate_size}, ${config.intermediate_size}]"` | `[12288, 12288]` |
| 循环下标 | `${loop_index}` | 当前迭代下标 |

- 支持 `+ - * /` 括号算术，以及 `config.is_moe` 之类的属性访问。
- 条件表达式：`condition: "config.swiglu_limit is not None"`、`"config.topk_method == 'noaux_tc'"`、`"not config.tie_word_embeddings"` 等。
- 自定义 config 由用户在 `assembly.config` 提供；未提供的表达式保留原文并在前端给出提示。

---

## 8. 可选字段：`forward_note` / `weight_prefix_note` / `note`

这三个是**备注类**字段，不参与连接逻辑，仅用于前端展示与溯源：

| 字段 | 适用 | 说明 |
|------|------|------|
| `forward_note` | composite/assembly | forward 计算的说明（如融合内核、残差路径） |
| `weight_prefix_note` | composite/assembly | 权重前缀映射说明（如 MTP 草稿权重前缀） |
| `note` | 任意 | 通用备注（挂在 composite 顶层或 step 上） |

---

## 9. `state`（可选，含内状态积木）

仅用于**有内部状态**的积木（如线性注意力/SSM 的卷积与循环状态）：

```yaml
state:
  - { form: conv_state, shape: "[B, ..., conv_size]" }
  - { form: recurrent_state, shape: "[B, num_heads, head_dim, head_dim]" }
```

---

## 10. 编写步骤（推荐流程）

以"用积木搭一个新模型"为例：

1. **列原子积木**：把模型用到的基础层列出来（embedding / norm / linear / activation / attention 内核 / MoE 内核 …），每一个写成一个 `atomic`。
   - 从 vLLM 源码找准类名、构造参数、源文件。
2. **组合中间结构**：把模型的重复模块（decoder layer、attention、mlp、moe、vision block…）拼成 `composite`，用 `children` + `edges` + 端口描述数据流。
   - 分支结构（dense vs moe、不同注意力类型）用 `condition` 表达。
   - 重复 N 层用 `loop`。
3. **写入口 assembly**：识别 vLLM 的**第一层入口类** → 写 `assembly`，`steps` 引用已定义的 composite/atomic，`edges` 描述顶层数据流，并**提供 `config`**。
4. **分区语义**：入口模型必须是 `assembly`；被入口持有的结构用 `composite`；单个不可分层用 `atomic`。
5. **自带 config**：每个入口 `assembly` 提供其 `config.json` 关键字段，确保 `${config.xxx}` 能解析。

---

## 11. 校验与导入

系统会在导入时做**静态校验**：
- 语法、`name` 唯一性、`kind` 合法性
- 引用的 `block`（在 children/steps 中）必须已被定义
- 端口连接的两端 `id` 必须存在
- `condition` / `loop.count` / `port_bind` 表达式可求值（依赖运行期 config 的会降级为 warning 而非 error）
- 允许 composite 嵌套 composite

导入方式：

在前端「模型拆分 → 模型 → 导入 YAML」界面粘贴 YAML 内容并导入；或将 YAML 内容通过 `POST /api/anatomy/import` 提交。
- 幂等：块/模型已存在则跳过（不覆盖），返回导入明细（成功/跳过/错误/警告）。
- 当前无独立 CLI 导入脚本：YAML 即唯一数据源，导入以导入接口为准。

---

## 12. 参考实现

完整可运行的示例见 `scripts/glm5_next_causal_lm.yaml`，它演示了 GLM-5.3-Flash 的全套：
- `atomic`：31 个（embedding/norm/linear/activation/attention/moe/head）
- `composite`：14 个（`Glm5NextDecoderLayer`、`Glm5NextMoE`、`Glm5NextMLAAttention`、`Glm5NextLinearAttention`、`Glm5NextModel`、`Glm5NextMultiTokenPredictor*`、`MHCMultiResidualStream`、视觉塔…）
- `assembly`：3 个入口（`Glm5NextForCausalLM`、`Glm5NextForConditionalGeneration`、`Glm5NextMTP`）

新模型可参考它的结构，用同样的三明治（atomic → composite → assembly）方式编排。