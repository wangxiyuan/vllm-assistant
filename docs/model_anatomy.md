# 模型拆解模块设计文档

> 版本：v1.0  
> 最后更新：2026-07-24

---

## 1. 背景与目标

### 1.1 背景

开源大模型迭代日新月异，vLLM 也在快速适配各种大模型。作为 vLLM 贡献者，需要掌握每一个大模型的结构。当前项目（vLLM Assistant）已有学习文章和代码浏览功能，但缺乏一个"模型结构可视化"的工具。

### 1.2 目标

设计一个"搭积木"式的模型拆解模块，让用户能：

1. **自定义创建算子**（积木块）—— 如 Embedding、RMSNorm、Attention 等
2. **用算子拼装成模型结构** —— 如 Qwen3.5、GLM5.2、DeepSeek V4 等
3. **可视化和对比**不同模型架构

---

## 2. 核心概念

本模块围绕三个核心实体设计：

### 2.1 算子（Operator）

积木块。每个算子代表一个神经网络层/组件，如 Embedding、RMSNorm、Attention、MLP、RotaryEmbedding 等。

**属性：**
- 名称、显示名称、描述
- 分类（embedding / normalization / attention / mlp / activation / positional / other）
- 参数定义（JSON Schema）—— 描述该算子的可配置参数
- 输入输出形状描述
- 关联的 vLLM 代码引用
- 标签

### 2.2 阶段（Stage）

模型结构中的一个"位置"。每个阶段可以是：

- **单算子** —— 一个算子实例，带具体参数配置
- **重复块** —— 多层重复结构（见下文）

### 2.3 模型（Model）

搭好的积木成品。模型由一系列"阶段（Stage）"组成，描述完整的模型架构。

---

## 3. 多层重复块（RepeatBlock）

这是核心设计概念。大模型最显著的结构特征就是"N 层相同的 Decoder Layer"。

### 3.1 基本结构

一个 repeat block 包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| type | `"repeat_block"` | 标记为重复块 |
| label | string | 块名称，如 "Transformer Layer" |
| repeat_count | int | 重复轮数 |
| contents | 数组的数组 | 多套内容，每套是一个有序算子列表 |

### 3.2 所有层相同（单套内容）

最常见的场景：32 层完全相同的 Decoder Layer。

```json
{
  "type": "repeat_block",
  "label": "Decoder Layer",
  "repeat_count": 32,
  "contents": [[
    { "type": "operator", "operator_name": "RMSNorm", "label": "Pre-Attention Norm", ... },
    { "type": "operator", "operator_name": "MultiHeadAttention", "label": "GQA Attention", ... },
    { "type": "operator", "operator_name": "RMSNorm", "label": "Post-Attention Norm", ... },
    { "type": "operator", "operator_name": "MLP", "label": "SwiGLU MLP", ... }
  ]]
}
```

实际层数 = `repeat_count × 套数` = `32 × 1 = 32 层`。

### 3.3 交替层不同（多套内容）

对于 1357 单数层和 2468 双数层结构不同的场景。

```json
{
  "type": "repeat_block",
  "label": "Decoder Layer (交替)",
  "repeat_count": 4,
  "contents": [
    [  // 第 1 套 —— 第 1、3、5、7 层
      { "type": "operator", "label": "Standard Attention", ... },
      { "type": "operator", "label": "Dense MLP", ... }
    ],
    [  // 第 2 套 —— 第 2、4、6、8 层
      { "type": "operator", "label": "Standard Attention", ... },
      { "type": "operator", "label": "MoE MLP", ... }
    ]
  ]
}
```

实际层数 = `repeat_count × 套数` = `4 × 2 = 8 层`。每轮按顺序遍历各套内容。

### 3.4 嵌套重复块

repeat_block 内部可以嵌套 repeat_block，以支持更复杂的重复结构（如某些模型在每 N 层之间插入一个特殊层）。

---

## 4. 数据模型

### 4.1 算子表（operators）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int, PK | 自增 ID |
| name | str | 算子名称（如 `RMSNorm`） |
| display_name | str | 显示名称（如 `RMS 归一化`） |
| description | text | 算子功能描述 |
| category | str | 分类 |
| params_schema | text(JSON) | 参数定义（JSON Schema） |
| input_shape_desc | str | 输入形状描述 |
| output_shape_desc | str | 输出形状描述 |
| vllm_code_refs | text(JSON) | 关联的 vLLM 代码引用列表 |
| tags | text(JSON) | 标签 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

### 4.2 模型表（models）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int, PK | 自增 ID |
| name | str | 模型名称（如 `Qwen3.5`） |
| display_name | str | 显示名称（如 `通义千问 3.5`） |
| description | text | 模型概述 |
| architecture | text(JSON) | 模型结构（JSON 数组） |
| params_summary | text(JSON) | 参数汇总 |
| operators_count | int | 使用的算子种类数 |
| tags | text(JSON) | 标签 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

### 4.3 architecture JSON 完整格式

```json
[
  // 单算子阶段
  {
    "type": "operator",
    "operator_id": 1,
    "operator_name": "Embedding",
    "params": { "vocab_size": 152064, "hidden_size": 8192 },
    "label": "Token Embedding",
    "children": [],
    "order": 0
  },
  // 重复块阶段（单套内容）
  {
    "type": "repeat_block",
    "label": "Transformer Layer",
    "repeat_count": 28,
    "contents": [[
      {
        "type": "operator",
        "operator_id": 2,
        "operator_name": "RMSNorm",
        "params": { "hidden_size": 8192, "eps": 1e-6 },
        "label": "Pre-Attention Norm",
        "children": [],
        "order": 0
      },
      {
        "type": "operator",
        "operator_id": 3,
        "operator_name": "MultiHeadAttention",
        "params": { "hidden_size": 8192, "num_heads": 64, "num_kv_heads": 8 },
        "label": "GQA Attention",
        "children": [
          {
            "type": "operator",
            "operator_id": 4,
            "operator_name": "RotaryEmbedding",
            "params": { "dim": 128, "max_position_embeddings": 131072 },
            "label": "RoPE",
            "children": [],
            "order": 0
          }
        ],
        "order": 1
      }
    ]]
  },
  // 重复块阶段（多套交替内容）
  {
    "type": "repeat_block",
    "label": "Decoder Layer (交替)",
    "repeat_count": 4,
    "contents": [
      [ /* 第 1 套 */ ],
      [ /* 第 2 套 */ ]
    ]
  }
]
```

---

## 5. 预置算子库

系统内置一批常见算子，开箱即用：

| 分类 | 算子 |
|------|------|
| Embedding | `Embedding`, `TokenEmbedding`, `WordEmbedding` |
| Normalization | `LayerNorm`, `RMSNorm` |
| Attention | `MultiHeadAttention`, `GroupedQueryAttention`, `MultiQueryAttention`, `CrossAttention`, `PagedAttention` |
| MLP | `MLP`, `SwiGLUMLP`, `GatedMLP`, `MoE`, `MoEBlock` |
| Activation | `SiLU`, `GELU`, `ReLU` |
| Positional | `RotaryEmbedding`, `ALiBi`, `SinusoidalPositionalEmbedding` |
| Pooling | `MeanPooling`, `AttentionPooling` |
| Output | `Linear`, `LMHead` |
| Other | `Dropout`, `ResidualConnection` |

用户也可以创建自定义算子，扩充算子库。

---

## 6. API 设计

### 6.1 算子 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/anatomy/operators` | 列出算子（支持 category/tag 筛选、搜索） |
| POST | `/api/anatomy/operators` | 创建新算子 |
| GET | `/api/anatomy/operators/{id}` | 获取算子详情 |
| PUT | `/api/anatomy/operators/{id}` | 更新算子 |
| DELETE | `/api/anatomy/operators/{id}` | 删除算子 |
| GET | `/api/anatomy/operators/categories` | 获取算子分类列表 |

### 6.2 模型 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/anatomy/models` | 列出模型 |
| POST | `/api/anatomy/models` | 创建新模型 |
| GET | `/api/anatomy/models/{id}` | 获取模型详情（含完整 architecture 树） |
| PUT | `/api/anatomy/models/{id}` | 更新模型 |
| DELETE | `/api/anatomy/models/{id}` | 删除模型 |

---

## 7. 前端设计

### 7.1 视图结构

侧边栏新增第 8 个入口"模型拆解"，快捷键 `8`。视图区域内部通过 tab 切换两个子视图。

### 7.2 子视图 A：算子管理

- 列表显示所有算子，按分类分组（卡片式布局）
- 每个算子卡片：图标/名称、分类标签、简短描述、参数概要
- 新建/编辑算子：弹窗内填写表单，参数 Schema 用 JSON 文本编辑器
- 搜索和分类筛选

### 7.3 子视图 B：模型搭建

**左侧面板** — 模型列表
- 列出所有已创建的模型
- 底部"新建模型"按钮

**右侧面板** — 模型详情/编辑器

**查看模式：**
- 模型基本信息
- 结构树可视化：缩进树形结构展示所有阶段
- `repeat_block` 节点显示 `[×N]` 标签，可展开内部结构
- 多套内容以 tab 形式展示"第 1 套"、"第 2 套"

**编辑模式：**
- 模型基本信息编辑区
- 阶段列表编辑器，每个阶段是一个可编辑行：
  - 类型切换：`单算子` / `重复块`
  - 单算子：选择算子 + 配置参数（动态表单，根据 params_schema 生成）
  - 重复块：设置重复次数 + 套数 + 每套独立编辑
  - 操作按钮：上移/下移/编辑/删除
  - 底部"添加阶段"按钮

---

## 8. 设计覆盖验证：DeepSeek V4

以 `vllm/models/deepseek_v4/nvidia/model.py` 为测试用例，验证设计覆盖能力。

### 8.1 DeepSeek V4 结构映射

```
DeepseekV4Model:
  ├── [Embedding] VocabParallelEmbedding
  ├── [RepeatBlock ×num_hidden_layers] DeepseekV4DecoderLayer
  │   ├── [RMSNorm] attn_norm
  │   ├── [MLA Attention] DeepseekV4Attention
  │   ├── [RMSNorm] ffn_norm
  │   └── [MoE] DeepseekV4MoE
  │       ├── [GateLinear] gate (Router)
  │       ├── [MLP] shared_experts (可选)
  │       └── [FusedMoE | MegaMoE] experts
  ├── [RMSNorm] norm (Final Norm)
  └── [HC Head] hc_head
```

### 8.2 覆盖矩阵

| 设计特性 | DeepSeek V4 中的应用 | 状态 |
|----------|---------------------|------|
| 单算子 | Embedding, RMSNorm, GateLinear | ✅ |
| 算子嵌套（children） | MoE 内部 Gate + Experts + SharedExpert | ✅ |
| repeat_block（单套） | 60 层同构 DecoderLayer | ✅ |
| 算子参数化 | hidden_size, num_attention_heads 等 | ✅ |
| 自定义算子 | MLA Attention, MegaMoE, HC Head | ✅ |
| 代码引用 | 引用对应类代码位置 | ✅ |

### 8.3 特殊结构处理

- **MLA Attention** → 注册为 `DeepseekV4MLA` 自定义算子，参数包含 `kv_lora_rank`、`qk_rope_head_dim` 等
- **MoE** → 注册为 `DeepseekV4MoE` 算子，内部嵌套子算子
- **HC (Heads Concatenation)** → 注册为 `HCHead` 算子

**结论：设计可以完整覆盖 DeepSeek V4 的架构表达。**

---

## 9. 目录结构

```
app/
  api/
    model_anatomy.py          # 算子 + 模型 CRUD API
  models.py                   # 新增 Operator, Model ORM 类
  schemas.py                  # 新增 Pydantic 请求/响应模型

static/
  js/
    model_anatomy.js          # Alpine.js mixin

docs/
  model_anatomy.md            # 本设计文档
```

---

## 10. 实现步骤

1. **数据库模型** — 在 `app/models.py` 中添加 `Operator` 和 `Model` 两个 ORM 类
2. **Pydantic Schema** — 在 `app/schemas.py` 中添加请求/响应模型
3. **API 路由** — 创建 `app/api/model_anatomy.py`，实现算子 CRUD 和模型 CRUD
4. **注册路由** — 在 `app/main.py` 注册 `/api/anatomy` 路由
5. **前端 JS mixin** — 创建 `static/js/model_anatomy.js`
6. **前端视图** — 在 `index.html` 中添加侧边栏入口和视图区域
7. **预置算子** — 初始化时自动创建一批常见算子
8. **验证** — 创建算子，搭建模型，验证多层重复块正确渲染