# 知识库向量检索升级 — 实现设计

## Context

当前知识库 (`ai_memory` 表) 使用 SQLite + FTS5 全文检索，存在以下局限：
1. **FTS5 中文分词弱** — `unicode61` tokenizer 按字分词，搜索"注意力机制"匹配不到"attention 机制"
2. **无语义搜索** — 关键词匹配不理解"性能优化"和"加速推理"是相关概念
3. **FTS5 相关性排序粗糙** — 简单的 TF-IDF 变体

目标：在现有 FTS5 基础上叠加 **embedding 向量检索**，实现关键词 + 语义混合召回，提升 10 人团队的 AI 对话体验。保持单容器部署，不引入外部数据库服务。

## 技术选型

### Embedding 方案：复用 OpenAI 兼容 API（项目已有的 LLM 接口）

项目中 `Config` 已配置 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`，LLM 通过 `openai` 库调用。绝大多数 OpenAI 兼容 API 都提供 `/v1/embeddings` 端点。

- **优点**：零新增依赖、零本地模型加载、API 直接调、Docker 镜像不增大
- **Embedding 模型建议**：`text-embedding-3-small`（1536 维，$0.02/1M tokens）或 `text-embedding-3-large`（3072 维），由 `EMBEDDING_MODEL` 环境变量配置

### 向量存储方案：sqlite-vec 扩展

`sqlite-vec` 是 SQLite 的原生向量扩展：
- 零外部服务，纯 SQLite 文件
- 支持 IVFFlat 索引加速 ANN 搜索
- 支持元数据过滤（和现有 `source_type`、`tags` 过滤无缝结合）
- Docker 镜像只需加一个 `.so` 文件

**备选**：如果 sqlite-vec 集成遇到平台兼容问题，降级为 `numpy` + 内存 Brute-force（10 人团队 1 万条记录，1536 维暴力搜索 < 10ms，完全够用）

## 架构设计

```
MemoryService.remember()
    │
    ├── 存 ai_memory 表（不变）
    ├── 更新 FTS5 全文索引（不变）
    └── 生成 embedding → 写入 ai_memory_vec 向量表（新增）

MemoryService.recall()
    │
    ├── FTS5 关键词检索（不变，保留）
    ├── Embedding 语义检索（新增）
    └── 混合排序（RRF: Reciprocal Rank Fusion）（新增）
```

## 详细设计

### 1. 新增配置项 (`app/config.py`)

```python
# Embedding 配置
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "1536"))  # 根据模型自动判断
# 混合检索权重
HYBRID_SEARCH_FTS_WEIGHT: float = float(os.getenv("HYBRID_SEARCH_FTS_WEIGHT", "0.3"))
HYBRID_SEARCH_VEC_WEIGHT: float = float(os.getenv("HYBRID_SEARCH_VEC_WEIGHT", "0.7"))
```

### 2. 新增 Embedding 服务 (`app/services/embedding_service.py`)

封装 embedding 生成逻辑：

```python
class EmbeddingService:
    def __init__(self):
        self.client = openai.AsyncOpenAI(
            api_key=Config.OPENAI_API_KEY,
            base_url=Config.OPENAI_BASE_URL,
        )
        self.model = Config.EMBEDDING_MODEL
    
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量生成 embedding"""
        resp = await self.client.embeddings.create(
            model=self.model,
            input=texts,
        )
        return [d.embedding for d in resp.data]
    
    async def embed_query(self, text: str) -> list[float]:
        """生成查询 embedding"""
        embeddings = await self.embed([text])
        return embeddings[0]
```

### 3. 新增向量存储表 (`app/database.py` 初始化逻辑)

- **方案 A（优先）：sqlite-vec 虚拟表**

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS ai_memory_vec USING vec0(
    embedding float[1536]
);
```

- **方案 B（备选）：纯 SQLite BLOB 表 + numpy 内存搜索**

```sql
CREATE TABLE IF NOT EXISTS ai_memory_vec (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER NOT NULL UNIQUE,
    embedding BLOB NOT NULL,  -- float32 数组序列化
    FOREIGN KEY (memory_id) REFERENCES ai_memory(id) ON DELETE CASCADE
);
```

搜的时候 `SELECT memory_id, embedding FROM ai_memory_vec` → `numpy` 计算 cosine similarity → TopK。

### 4. 改造 `MemoryService.remember()` (`app/services/memory_service.py`)

在存储知识条目后，异步生成 embedding：

```python
def remember(self, content, ...):
    # ... 现有逻辑不变 ...
    
    # 增量：为新/更新的条目生成 embedding
    if entry_id:
        self._schedule_embedding_sync(entry_id, content)  # 不阻塞，后台执行
    
    return entry_id
```

同步逻辑：
- 读取 `content` 前 8000 字符（embedding 模型的 token 限制）
- 调用 `EmbeddingService.embed()`
- 写入 `ai_memory_vec` 表（INSERT OR REPLACE）

### 5. 改造 `MemoryService.recall()` (`app/services/memory_service.py`)

混合检索流程：

```python
def recall(self, query, top_k=5, ...):
    # 1. FTS5 检索（现有逻辑，不变）
    fts_results = self._fts_search(query, top_k * 2)
    
    # 2. 向量检索（新增）
    vec_results = self._vector_search(query, top_k * 2)
    
    # 3. RRF 混合排序
    merged = self._rrf_merge(fts_results, vec_results, top_k,
                             fts_weight=0.3, vec_weight=0.7)
    
    # 4. 更新访问统计（不变）
    return merged
```

RRF 算法：
```python
def _rrf_merge(self, fts_list, vec_list, top_k, fts_weight, vec_weight):
    scores = {}
    k = 60  # RRF 平滑常数
    
    for rank, item in enumerate(fts_list):
        scores[item.id] = scores.get(item.id, 0) + fts_weight / (k + rank + 1)
    
    for rank, item in enumerate(vec_list):
        scores[item.id] = scores.get(item.id, 0) + vec_weight / (k + rank + 1)
    
    sorted_ids = sorted(scores, key=scores.get, reverse=True)[:top_k]
    return [self._get_entry(id) for id in sorted_ids]
```

### 6. 初始化时批量生成 embedding (`app/main.py`)

在 `_init_knowledge_base()` 中增加一步：检查缺失 embedding 的条目，批量生成。

### 7. 工具扩展 (`app/services/tools/knowledge_tools.py`)

`search_memory` 工具调用 `MemoryService.recall()` 的接口不变，内部自动走混合检索，对 AI 透明。

### 8. 环境变量 (`app/config.py`)

新增：
```python
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
HYBRID_SEARCH_FTS_WEIGHT: float = float(os.getenv("HYBRID_SEARCH_FTS_WEIGHT", "0.3"))
HYBRID_SEARCH_VEC_WEIGHT: float = float(os.getenv("HYBRID_SEARCH_VEC_WEIGHT", "0.7"))
```

### 9. 依赖更新 (`requirements.txt`)

新增：
```
numpy==2.2.1
```

（如果用 sqlite-vec，加 `sqlite-vec`；如果纯 numpy 暴力搜索，只需 numpy）

## 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Embedding 来源 | OpenAI 兼容 API | 已有配置，零成本接入，不增加容器体积 |
| 向量存储 | 优先 sqlite-vec，备选 numpy BLOB | sqlite-vec 优雅但需编译扩展；numpy 暴力搜索在 1 万条记录内性能足够 |
| FTS5 是否保留 | 保留，做混合检索 | FTS5 对精确关键词匹配（函数名、文件名）仍然优秀，和语义搜索互补 |
| 混合算法 | RRF | 工业界标准做法，无需调参 |
| 同步时机 | remember() 中同步生成 | 保持简单；未来可改为队列异步 |
| 接口兼容 | `recall()` 签名不变 | 调用方无需改动 |

## 文件变更清单

| 文件 | 变更 |
|------|------|
| `app/config.py` | 新增 3 个 embedding 配置项 |
| `requirements.txt` | 新增 `numpy` |
| `app/services/embedding_service.py` | **新文件** — Embedding API 封装 |
| `app/services/memory_service.py` | `remember()` 加 embedding 生成，`recall()` 加混合检索 |
| `app/database.py` | 新增向量表初始化逻辑 |
| `app/main.py` | `_init_knowledge_base()` 加 embedding 批量补全 |
| `.env.example` | 新增 embedding 配置示例 |
| `Dockerfile` | 如果选 sqlite-vec，需要编译/安装扩展 |

## 验证方案

1. **单元测试**：用 `embeddings.list` 接口验证 embedding 生成和存储
2. **功能验证**：往知识库插入带"性能优化"内容的条目，用"加速推理"搜索，验证能命中
3. **回归验证**：确认 `search_memory` 工具 + AI 对话链路正常工作
4. **性能验证**：1 万条记录下 `recall()` 延迟 < 200ms
5. **部署验证**：`docker-compose up` 正常启动，`data/` 目录下 `vllm_assistant.db` 包含新表且大小合理（增加量 ≈ 1万 × 1536 × 4B = ~60MB）