# 学习文章管理系统 - 设计文档

## 1. 概述

### 1.1 背景
作为 vllm-ascend 项目的 committer，在学习和贡献过程中撰写了大量学习文章，包括：
- vLLM 源码分析笔记
- 功能实现原理解读
- 调试经验总结
- 技术方案对比

这些文章目前分散存储，且存在以下问题：
- **内容过时**：vLLM 代码频繁更新，文章中的代码引用可能已失效
- **无法验证**：无法快速确认文中引用的代码是否仍然准确
- **缺乏组织**：没有统一的分类和检索机制

### 1.2 目标
- 提供内置 Markdown 编辑器，集中存储学习文章
- 支持相对路径 + 行号格式的代码引用（如 `vllm/engine/core.py:10-20`）
- **渲染文章时自动嵌入对应代码片段**，无需手动复制粘贴
- 定时后台验证代码引用的有效性（两阶段：行号检查 + 内容哈希校验）
- 页面内标记过时内容，提醒用户更新

### 1.3 非目标
- 不支持实时协作编辑
- 不需要完整的版本历史记录
- 不实现文章发布/分享功能
- 不支持图片/附件上传
- 不是完整的 IDE，只做代码片段嵌入预览

---

## 2. 数据模型

### 2.1 Article（文章）

```python
class Article(Base):
    """学习文章"""
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)               # 文章标题
    content = Column(Text, nullable=False)              # Markdown 原文
    rendered_html = Column(Text)                        # 渲染后的 HTML（缓存）

    # 元信息
    area = Column(String(50))                           # 所属领域 (engine/model/...)
    tags = Column(Text)                                 # JSON array
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    # 状态
    status = Column(String(20), nullable=False, default="draft")  # draft / published / archived

    # 代码引用统计
    code_refs_count = Column(Integer, default=0)        # 文中代码引用总数
    valid_refs_count = Column(Integer, default=0)       # 有效的引用数
    outdated_refs_count = Column(Integer, default=0)    # 过时的引用数

    # 最后验证时间
    last_verified_at = Column(DateTime)                 # 最后代码验证时间

    # ORM 关系
    refs = relationship("CodeReference", back_populates="article",
                        cascade="all, delete-orphan")
```

### 2.2 CodeReference（代码引用记录）

```python
class CodeReference(Base):
    """文章中的代码引用记录"""
    __tablename__ = "code_references"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)

    # 引用位置（在文章中的位置，用于快速定位）
    article_line_start = Column(Integer)                # 起始行号（文章内容中的行）
    article_line_end = Column(Integer)                  # 结束行号

    # 引用目标
    repo_name = Column(String(100), nullable=False)     # 仓库名，如 vllm、vllm-ascend
    file_path = Column(String(500), nullable=False)     # 仓库内相对路径
    line_start = Column(Integer, nullable=False)        # 起始行号
    line_end = Column(Integer)                          # 结束行号

    # 引用内容快照（保存时截取，用于后续判断内容是否变化）
    content_snapshot = Column(Text)                     # 保存时的代码内容
    content_hash = Column(String(64))                   # 保存时的 SHA256

    # 验证状态
    last_checked_at = Column(DateTime)
    is_valid = Column(Boolean, default=True)            # 当前是否有效
    current_content = Column(Text)                      # 当前代码内容（用于渲染预览）
    diff_summary = Column(Text)                         # 变化摘要

    # ORM 关系
    article = relationship("Article", back_populates="refs")
```

### 2.3 LocalCodeCache（本地代码缓存）

```python
class LocalCodeCache(Base):
    """本地代码缓存（按仓库隔离）"""
    __tablename__ = "local_code_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo = Column(String(100), nullable=False, default="vllm")  # 仓库名
    file_path = Column(String(500), nullable=False)              # 仓库内相对路径
    content = Column(Text)                                       # 文件完整内容
    last_synced_at = Column(DateTime, nullable=False)
    checksum = Column(String(64))                                # SHA256 校验
    total_lines = Column(Integer)                                # 总行数

    __table_args__ = (
        UniqueConstraint("repo", "file_path", name="uq_repo_file"),
    )
```

### 2.4 RepoCache（仓库缓存管理）

```python
class RepoCache(Base):
    """已缓存的本地仓库记录"""
    __tablename__ = "repo_caches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo = Column(String(100), unique=True, nullable=False)  # 仓库名
    clone_url = Column(String(500), nullable=False)           # Git URL
    local_path = Column(String(500), nullable=False)          # 本地路径
    branch = Column(String(50), default="main")               # 跟踪分支
    last_synced_at = Column(DateTime)                         # 最后一次 git pull
    commit_sha = Column(String(40))                           # 当前 HEAD
```

---

## 3. 代码仓库管理

### 3.1 仓库配置

在 `.env` 中配置需要同步的代码仓库：

```ini
# 代码仓库列表（逗号分隔，格式：name=url, name=url）
# 每个仓库的 watch_dirs 通过 WATCH_DIRS_{NAME} 单独配置
REPOS=vllm=https://github.com/vllm-project/vllm.git,vllm-ascend=https://github.com/wangxiyuan/vllm-ascend.git

# 各仓库的关注目录（用于同步到缓存）
WATCH_DIRS_VLLM=vllm/engine,vllm/model_executor,vllm/worker,vllm/scheduler,vllm/attention
WATCH_DIRS_VLLM_ASCEND=ascend

# 代码同步间隔（分钟）
CODE_SYNC_INTERVAL=30
```

### 3.2 启动时 clone

服务启动时（lifespan），后台异步 clone 各仓库的 `main` 分支到 `data/repos/{name}/`：

```
data/repos/vllm/          ← git clone --branch main --depth 1
data/repos/vllm-ascend/   ← git clone --branch main --depth 1
```

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动 scheduler
    start_scheduler()

    # 后台异步 clone 代码仓库（不阻塞服务启动）
    asyncio.create_task(init_repo_caches())

    yield
    stop_scheduler()


async def init_repo_caches():
    """异步初始化所有代码仓库：clone 或 pull"""
    from app.services.repo_manager import RepoManager

    manager = RepoManager()
    for repo_name, clone_url in Config.REPOS.items():
        try:
            await manager.async_ensure_cloned(repo_name, clone_url, branch="main")
        except Exception:
            logger.exception(f"Failed to clone repo {repo_name}")
```

### 3.3 定时同步

定时任务中，先 `git pull --ff-only` 更新本地仓库，然后同步到 `LocalCodeCache`：

```
定时任务触发
    ↓
git pull --ff-only origin main   ← 更新工作副本
    ↓
checksum 变化？ → 更新 LocalCodeCache
    ↓
对变更的文件重新验证相关文章的 CodeReference（行号检查）
    ↓
结束
```

```python
def sync_all_repos():
    """定时任务：拉取最新代码并更新缓存"""
    from app.services.repo_manager import RepoManager

    manager = RepoManager()
    for repo_name in Config.REPOS:
        result = manager.pull_and_sync(repo_name)
        logger.info(f"Repo {repo_name} synced: {result}")

    # 对所有受影响文件做行号越界检查
    manager.validate_all_refs()
```

---

## 4. API 设计

### 4.1 文章管理

```
GET    /api/articles
POST   /api/articles
PUT    /api/articles/{article_id}
DELETE /api/articles/{article_id}
GET    /api/articles/{article_id}/rendered  # 渲染后的文章（含嵌入代码）
POST   /api/articles/{article_id}/preview  # 预览（不保存，返回渲染结果）
```

#### GET /api/articles

获取文章列表。

**Query Parameters:**
| 参数 | 类型 | 说明 |
|------|------|------|
| area | string | 筛选领域 |
| status | string | 筛选状态：all / draft / published / archived |
| tag | string | 筛选标签 |
| sort_by | string | 排序字段：created / updated / title |
| sort_order | string | 排序方向：asc / desc |

**Response:**
```json
{
  "articles": [
    {
      "id": 1,
      "title": "vLLM Engine 架构解析",
      "area": "engine",
      "tags": ["architecture", "source-code"],
      "status": "published",
      "code_refs_count": 15,
      "valid_refs_count": 12,
      "outdated_refs_count": 3,
      "last_verified_at": "2024-01-20T10:00:00Z",
      "created_at": "2024-01-15T08:00:00Z",
      "updated_at": "2024-01-25T14:30:00Z"
    }
  ],
  "total": 25
}
```

#### POST /api/articles

创建新文章。保存时自动解析代码引用，写入 `CodeReference` 表并记录 `content_hash`。

**Request Body:**
```json
{
  "title": "vLLM Engine 架构解析",
  "content": "# vLLM Engine 架构\n\n本文分析 vLLM 的核心引擎架构...",
  "area": "engine",
  "tags": ["architecture", "source-code"],
  "status": "draft"
}
```

**Response:**
```json
{
  "id": 1,
  "title": "vLLM Engine 架构解析",
  "status": "draft",
  "created_at": "2024-01-15T08:00:00Z",
  "refs_count": 5
}
```

#### PUT /api/articles/{article_id}

更新文章内容。保存时重新解析代码引用（增量更新策略），更新 `content_hash` 和 `content_snapshot`。

**Request Body:**
```json
{
  "title": "vLLM Engine 架构解析（更新版）",
  "content": "# vLLM Engine 架构\n\n更新后的内容...",
  "area": "engine",
  "tags": ["architecture", "source-code", "updated"]
}
```

**Response:**
```json
{
  "id": 1,
  "title": "vLLM Engine 架构解析（更新版）",
  "updated_at": "2024-01-25T14:30:00Z",
  "refs_count": 5
}
```

#### DELETE /api/articles/{article_id}

删除文章。级联删除所有关联的 `CodeReference`。

#### POST /api/articles/{article_id}/preview

预览文章渲染结果（不保存到数据库）。

**Request Body:**
```json
{
  "content": "# vLLM Engine 架构\n\n核心循环位于 `vllm/engine/core.py:10-50`"
}
```

**Response:**
```json
{
  "html": "<h1>vLLM Engine 架构</h1><p>核心循环位于：</p><pre><code>...</code></pre>",
  "refs": [
    {
      "file_path": "vllm/engine/core.py",
      "line_start": 10,
      "line_end": 50,
      "is_valid": true,
      "content_snippet": "def core_loop():\n    ..."
    }
  ]
}
```

#### GET /api/articles/{article_id}/rendered

获取渲染后的文章 HTML，代码引用会被替换为实际代码片段。

**Query Parameters:**
| 参数 | 类型 | 说明 |
|------|------|------|
| sync_code | boolean | 是否先同步本地代码再渲染（默认 false） |

**Response:**
```json
{
  "id": 1,
  "title": "vLLM Engine 架构解析",
  "html": "<h1>...</h1>...",
  "embedded_codes": [
    {
      "ref_id": 123,
      "repo": "vllm",
      "file_path": "vllm/engine/core.py",
      "line_start": 10,
      "line_end": 20,
      "is_valid": true,
      "total_lines": 150
    }
  ]
}
```

### 4.2 代码引用验证

```
POST   /api/articles/{article_id}/validate
POST   /api/articles/batch-validate
```

#### POST /api/articles/{article_id}/validate

验证单篇文章中的所有代码引用。

**Request Body:**
```json
{
  "deep_check": false       // true 时做内容哈希校验（慢），false 只做行号越界检查
}
```

**Response:**
```json
{
  "article_id": 1,
  "validated_at": "2024-01-25T14:35:00Z",
  "total_refs": 15,
  "valid_refs": 12,
  "invalid_refs": 3,
  "details": [
    {
      "repo": "vllm",
      "file_path": "vllm/engine/core.py",
      "line_start": 10,
      "line_end": 20,
      "is_valid": true,
      "content_snippet": "def core_loop():\n    ...",
      "message": ""
    },
    {
      "repo": "vllm",
      "file_path": "vllm/scheduler/policy.py",
      "line_start": 45,
      "line_end": 50,
      "is_valid": false,
      "reason": "content_changed",
      "message": "代码内容已变更，请查看文章确认是否需要更新",
      "diff_summary": "@@ -10,5 +10,5 @@\n do_something()\n-do_old_thing()\n+do_new_thing()\n return result"
    }
  ]
}
```

### 4.3 代码缓存查询

```
GET    /api/code/{file_path:path}
POST   /api/code/embed
```

#### GET /api/code/{file_path}

获取缓存的代码文件内容（用于前端跳转预览）。支持跨仓库查询。

**Query Parameters:**
| 参数 | 类型 | 说明 |
|------|------|------|
| repo | string | 仓库名（默认 vllm） |
| line_start | integer | 起始行号（可选） |
| line_end | integer | 结束行号（可选） |

**Response:**
```json
{
  "repo": "vllm",
  "file_path": "vllm/engine/core.py",
  "content": "def core_loop():\n    ...\n",
  "total_lines": 150,
  "checksum": "abc123...",
  "last_synced_at": "2024-01-25T14:40:00Z"
}
```

#### POST /api/code/embed

批量获取多个代码片段，用于文章渲染时嵌入。

**Request Body:**
```json
{
  "refs": [
    {"repo": "vllm", "file_path": "vllm/engine/core.py", "line_start": 10, "line_end": 20},
    {"repo": "vllm-ascend", "file_path": "ascend/backend.py", "line_start": 1, "line_end": 5}
  ]
}
```

**Response:**
```json
{
  "snippets": [
    {
      "repo": "vllm",
      "file_path": "vllm/engine/core.py",
      "line_start": 10,
      "line_end": 20,
      "is_valid": true,
      "content": "def core_loop():\n    ...",
      "html": "<pre><code>...</code></pre>"
    }
  ]
}
```

---

## 5. 核心服务设计

### 5.1 RepoManager（仓库管理服务）

```python
# app/services/repo_manager.py

import os
import hashlib
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from app.config import Config
from app.database import SessionLocal

logger = logging.getLogger(__name__)


class RepoManager:
    """多仓库管理：clone、pull、同步到缓存"""

    CACHE_DIR = Config.BASE_DIR / "data" / "repos"

    def __init__(self):
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def get_local_path(self, repo_name: str) -> Path:
        """获取仓库本地路径"""
        return self.CACHE_DIR / repo_name

    async def async_ensure_cloned(self, repo_name: str, clone_url: str, branch: str = "main"):
        """
        异步确保仓库已 clone（不阻塞服务启动）。
        已存在则 git pull --ff-only，不存在则 git clone --depth 1。
        """
        local_path = self.get_local_path(repo_name)
        if local_path.exists():
            # 已存在，异步 pull
            proc = await asyncio.create_subprocess_exec(
                "git", "pull", "--ff-only", "origin", branch,
                cwd=str(local_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning(f"git pull failed for {repo_name}: {stderr.decode()}")
            else:
                logger.info(f"git pull succeeded for {repo_name}")
        else:
            # 不存在，异步 clone（depth=1 只拉最新 commit）
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", "--branch", branch, "--depth", "1",
                clone_url, str(local_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error(f"git clone failed for {repo_name}: {stderr.decode()}")
                raise RuntimeError(f"Failed to clone {repo_name}: {stderr.decode()}")
            logger.info(f"git clone succeeded for {repo_name}")

    def pull_and_sync(self, repo_name: str) -> Dict:
        """
        同步单个仓库：git pull → 更新 LocalCodeCache。
        串行执行（SQLite 不支持并发写）。
        """
        local_path = self.get_local_path(repo_name)
        if not local_path.exists():
            return {"status": "not_cloned", "repo": repo_name}

        # git pull
        import subprocess
        result = subprocess.run(
            ["git", "pull", "--ff-only", "origin", "main"],
            cwd=str(local_path), capture_output=True, text=True,
        )
        if result.returncode != 0:
            return {"status": "pull_failed", "repo": repo_name, "error": result.stderr}

        # 同步到 LocalCodeCache
        db = SessionLocal()
        try:
            stats = self._sync_to_cache(repo_name, local_path, db)
            db.commit()
            return {"status": "ok", "repo": repo_name, **stats}
        except Exception:
            db.rollback()
            logger.exception(f"Sync to cache failed for {repo_name}")
            return {"status": "sync_failed", "repo": repo_name}
        finally:
            db.close()

    def _sync_to_cache(self, repo_name: str, local_path: Path, db) -> Dict:
        """扫描 watch_dirs 下的 .py 文件，更新 LocalCodeCache"""
        from app.models import LocalCodeCache

        watch_dirs = Config.get_watch_dirs(repo_name)
        stats = {"created": 0, "updated": 0, "unchanged": 0, "errors": []}

        for watch_dir in watch_dirs:
            base_path = local_path / watch_dir
            if not base_path.exists():
                continue

            for py_file in sorted(base_path.rglob("*.py")):
                relative_path = str(py_file.relative_to(local_path)).replace("\\", "/")
                result = self._sync_file(repo_name, relative_path, py_file, db)
                if result["status"] == "created":
                    stats["created"] += 1
                elif result["status"] == "updated":
                    stats["updated"] += 1
                elif result["status"] == "unchanged":
                    stats["unchanged"] += 1
                else:
                    stats["errors"].append(result)

        return stats

    def _sync_file(self, repo: str, relative_path: str, full_path: Path, db) -> Dict:
        """同步单个文件到 LocalCodeCache"""
        try:
            content = full_path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(content.encode()).hexdigest()
            lines = content.split("\n")

            cached = db.query(LocalCodeCache).filter(
                LocalCodeCache.repo == repo,
                LocalCodeCache.file_path == relative_path,
            ).first()

            if cached:
                if cached.checksum != checksum:
                    cached.content = content
                    cached.checksum = checksum
                    cached.total_lines = len(lines)
                    cached.last_synced_at = datetime.utcnow()
                    return {"status": "updated", "path": relative_path}
                return {"status": "unchanged", "path": relative_path}
            else:
                db.add(LocalCodeCache(
                    repo=repo,
                    file_path=relative_path,
                    content=content,
                    checksum=checksum,
                    total_lines=len(lines),
                    last_synced_at=datetime.utcnow(),
                ))
                return {"status": "created", "path": relative_path}
        except Exception as e:
            logger.exception(f"Error syncing file {relative_path}")
            return {"status": "error", "path": relative_path, "error": str(e)}

    def validate_all_refs(self):
        """对所有受影响的文件做行号越界检查（轻量验证）"""
        from app.models import CodeReference, Article
        from app.services.local_code_sync import LocalCodeSyncService

        db = SessionLocal()
        try:
            cache_service = LocalCodeSyncService(db)
            refs = db.query(CodeReference).all()
            for ref in refs:
                lines = cache_service.get_file_lines(ref.repo, ref.file_path)
                if lines is None:
                    continue
                total_lines = len(lines)
                if ref.line_start > total_lines or ref.line_end > total_lines:
                    ref.is_valid = False
                    ref.last_checked_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()
```

### 5.2 CodeRefParser（代码引用解析器）

```python
# app/services/code_ref_parser.py

import re
import hashlib
from typing import List, Dict, Optional

from app.config import Config


class CodeRefParser:
    """解析 Markdown 中的代码引用，支持多仓库"""

    def __init__(self):
        # 从配置中获取所有仓库名，构建正则前缀
        # 如 ["vllm", "vllm-ascend"] → "(?:vllm|vllm-ascend)"
        self.repo_names = sorted(Config.REPOS.keys(), key=len, reverse=True)
        prefix_pattern = "|".join(re.escape(n) for n in self.repo_names)

        # 匹配格式（反引号必须成对出现，避免误匹配）：
        #   `vllm/engine/core.py:10-20`
        #   `vllm/engine/core.py:L10-L20`
        #   `vllm-ascend/ascend/backend.py:30`
        self.REF_PATTERN = re.compile(
            rf'`(?:{prefix_pattern})/([^`\s]+?)[:#]L?(\d+)(?:[-~]L?(\d+))?`'
        )

    def parse_article(self, content: str) -> List[Dict]:
        """
        解析文章中的所有代码引用

        Returns:
            List of {
                "article_line": 行号,
                "repo": 仓库名,
                "file_path": 仓库内路径,
                "line_start": 起始行,
                "line_end": 结束行,
                "raw_match": 原始匹配文本
            }
        """
        lines = content.split('\n')
        results = []

        for line_idx, line in enumerate(lines, 1):
            matches = self.REF_PATTERN.finditer(line)
            for match in matches:
                # 反推仓库名：从全文匹配中提取前缀
                full_match = match.group(0)
                # 找到匹配的仓库前缀
                repo = self._detect_repo(full_match)
                file_path = match.group(1)
                start_line = int(match.group(2))
                end_line = int(match.group(3)) if match.group(3) else start_line

                results.append({
                    "article_line": line_idx,
                    "repo": repo,
                    "file_path": file_path,
                    "line_start": start_line,
                    "line_end": end_line,
                    "raw_match": full_match,
                })

        return results

    def _detect_repo(self, match: str) -> str:
        """从匹配文本中检测仓库名"""
        for name in self.repo_names:
            if match.startswith(f"`{name}/") or match.startswith(name + "/"):
                return name
        return self.repo_names[0]  # fallback 到第一个仓库

    def validate_ref(self, repo: str, file_path: str, start_line: int, end_line: int,
                     cache_service) -> Dict:
        """
        验证单个引用是否有效。

        行号检查：文件是否缓存 → 行号是否越界
        深度检查：基于 content_hash 判断内容是否变化（由调用方决定是否执行）
        """
        from app.models import LocalCodeCache

        lines = cache_service.get_file_lines(repo, file_path)
        if lines is None:
            return {
                "valid": False,
                "reason": "file_not_cached",
                "message": f"文件 {repo}/{file_path} 未在缓存中，请先执行代码同步",
            }

        total_lines = len(lines)
        if start_line > total_lines or end_line > total_lines:
            return {
                "valid": False,
                "reason": "line_out_of_range",
                "message": f"行号超出范围（文件当前共 {total_lines} 行）",
                "expected_range": f"1-{total_lines}",
                "actual_range": f"{start_line}-{end_line}",
            }

        # 提取引用的代码片段
        referenced_content = "\n".join(lines[start_line - 1:end_line])
        current_hash = hashlib.sha256(referenced_content.encode()).hexdigest()

        return {
            "valid": True,
            "reason": "ok",
            "content": referenced_content,
            "content_hash": current_hash,
            "total_lines": total_lines,
        }

    def deep_validate(self, ref, db) -> Dict:
        """
        深度检查：对比保存时的 content_hash 与当前代码的 hash。
        用于定时任务，检测"同行号但内容已变"的情况。

        Args:
            ref: CodeReference 对象（必须是 db session 关联的，非 detached）
            db: 数据库 session（统一由调用方传入）
        """
        from app.services.local_code_sync import LocalCodeSyncService

        cache_service = LocalCodeSyncService(db)
        lines = cache_service.get_file_lines(ref.repo, ref.file_path)
        if lines is None:
            return {"valid": False, "reason": "file_not_cached"}

        if ref.line_start > len(lines) or ref.line_end > len(lines):
            return {"valid": False, "reason": "line_out_of_range"}

        current_content = "\n".join(lines[ref.line_start - 1:ref.line_end])
        current_hash = hashlib.sha256(current_content.encode()).hexdigest()

        if current_hash != ref.content_hash:
            # 内容变了！生成 diff 摘要
            diff_summary = self._generate_diff_summary(
                ref.content_snapshot or "", current_content
            )
            return {
                "valid": False,
                "reason": "content_changed",
                "old_content": ref.content_snapshot,
                "new_content": current_content,
                "diff_summary": diff_summary,
            }

        return {"valid": True, "reason": "ok", "content": current_content}

    def _generate_diff_summary(self, old: str, new: str) -> str:
        """生成简单的 diff 摘要（行级别对比）"""
        import difflib
        old_lines = old.splitlines()
        new_lines = new.splitlines()
        diff = difflib.unified_diff(old_lines, new_lines, n=2)
        return "\n".join(diff)

    def get_snippet_html(self, repo: str, file_path: str, start_line: int, end_line: int,
                         cache_service, show_line_numbers: bool = True,
                         is_outdated: bool = False) -> str:
        """生成代码片段的 HTML"""
        lines = cache_service.get_file_lines(repo, file_path)
        if lines is None:
            return '<div class="code-embed-error">文件未缓存</div>'

        total_lines = len(lines)
        if start_line > total_lines or end_line > total_lines:
            return f'<div class="code-embed-error">行号超出范围（文件共 {total_lines} 行）</div>'

        snippet_lines = lines[start_line - 1:end_line]
        css_class = "embedded-code outdated" if is_outdated else "embedded-code"
        html_parts = [f'<pre><code class="{css_class}" data-repo="{repo}" data-file="{file_path}" data-line-start="{start_line}" data-line-end="{end_line}">']

        # 如果过时，在顶部显示提示
        if is_outdated:
            html_parts.append('<div class="outdated-banner">⚠️ 此代码引用可能已过时</div>')

        for i, line in enumerate(snippet_lines, start_line):
            if show_line_numbers:
                html_parts.append(f'<span class="line-number">{i:>4}</span> ')
            escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            html_parts.append(f'<span class="code-content">{escaped}</span>\n')

        html_parts.append('</code></pre>')
        return ''.join(html_parts)

    def save_article_refs(self, article_id: int, content: str, db) -> Dict:
        """
        保存文章时，解析所有代码引用并写入 CodeReference 表。

        在 POST/PUT /api/articles 的 handler 中调用。
        记录 content_hash 和 content_snapshot，用于后续深度检查。
        """
        from app.models import CodeReference, Article
        from app.services.local_code_sync import LocalCodeSyncService

        refs = self.parse_article(content)
        cache_service = LocalCodeSyncService(db)

        # 删除不再存在的引用
        existing = db.query(CodeReference).filter(
            CodeReference.article_id == article_id
        ).all()
        existing_keys = {(r.repo, r.file_path, r.line_start, r.line_end) for r in existing}
        current_keys = {(r["repo"], r["file_path"], r["line_start"], r["line_end"])
                        for r in refs}
        for ref in existing:
            key = (ref.repo, ref.file_path, ref.line_start, ref.line_end)
            if key not in current_keys:
                db.delete(ref)

        # 新增或更新引用，记录 content_hash
        valid_count = 0
        for ref_data in refs:
            key = (ref_data["repo"], ref_data["file_path"],
                   ref_data["line_start"], ref_data["line_end"])

            # 获取当前代码内容并计算 hash
            lines = cache_service.get_file_lines(
                ref_data["repo"], ref_data["file_path"]
            )
            content_snapshot = None
            content_hash = None
            if lines and ref_data["line_start"] <= len(lines):
                snippet = "\n".join(
                    lines[ref_data["line_start"] - 1:ref_data["line_end"]]
                )
                content_snapshot = snippet
                content_hash = hashlib.sha256(snippet.encode()).hexdigest()

            existing_ref = db.query(CodeReference).filter(
                CodeReference.article_id == article_id,
                CodeReference.repo == ref_data["repo"],
                CodeReference.file_path == ref_data["file_path"],
                CodeReference.line_start == ref_data["line_start"],
                CodeReference.line_end == ref_data["line_end"],
            ).first()

            if existing_ref:
                existing_ref.content_snapshot = content_snapshot
                existing_ref.content_hash = content_hash
                existing_ref.last_checked_at = datetime.utcnow()
            else:
                db.add(CodeReference(
                    article_id=article_id,
                    article_line_start=ref_data["article_line"],
                    repo=ref_data["repo"],
                    file_path=ref_data["file_path"],
                    line_start=ref_data["line_start"],
                    line_end=ref_data["line_end"],
                    content_snapshot=content_snapshot,
                    content_hash=content_hash,
                    last_checked_at=datetime.utcnow(),
                ))

            if content_hash:
                valid_count += 1

        # 更新文章统计
        article = db.query(Article).filter(Article.id == article_id).first()
        if article:
            article.code_refs_count = len(refs)
            article.valid_refs_count = valid_count

        db.commit()
        return {"total_refs": len(refs), "valid_refs": valid_count}
```

### 5.3 LocalCodeSyncService（代码缓存查询服务）

```python
# app/services/local_code_sync.py

from typing import List, Optional
from app.models import LocalCodeCache


class LocalCodeSyncService:
    """只读缓存查询服务（不负责同步，同步由 RepoManager 负责）"""

    def __init__(self, db):
        self.db = db

    def get_file_lines(self, repo: str, file_path: str) -> Optional[List[str]]:
        """获取缓存的文件行列表"""
        cached = self.db.query(LocalCodeCache).filter(
            LocalCodeCache.repo == repo,
            LocalCodeCache.file_path == file_path,
        ).first()
        if cached:
            return cached.content.split("\n")
        return None

    def get_file_content(self, repo: str, file_path: str) -> Optional[str]:
        """获取缓存的文件内容"""
        cached = self.db.query(LocalCodeCache).filter(
            LocalCodeCache.repo == repo,
            LocalCodeCache.file_path == file_path,
        ).first()
        return cached.content if cached else None

    def batch_get_snippets(self, refs: List[dict]) -> List[dict]:
        """批量获取代码片段"""
        results = []
        for ref in refs:
            repo = ref.get("repo", "vllm")
            file_path = ref["file_path"]
            start_line = ref["line_start"]
            end_line = ref.get("line_end", start_line)

            lines = self.get_file_lines(repo, file_path)
            if lines is None or start_line > len(lines) or end_line > len(lines):
                results.append({
                    "repo": repo,
                    "file_path": file_path,
                    "line_start": start_line,
                    "line_end": end_line,
                    "is_valid": False,
                    "reason": "line_out_of_range",
                })
            else:
                content = "\n".join(lines[start_line - 1:end_line])
                results.append({
                    "repo": repo,
                    "file_path": file_path,
                    "line_start": start_line,
                    "line_end": end_line,
                    "is_valid": True,
                    "content": content,
                })
        return results
```

### 5.4 ArticleRenderer（文章渲染器）

```python
# app/services/article_renderer.py

import re
from typing import Dict, List
from markdown import markdown

from app.models import CodeReference


class ArticleRenderer:
    """渲染文章，将代码引用替换为实际代码片段"""

    def __init__(self, cache_service: LocalCodeSyncService, db):
        self.cache_service = cache_service
        self.db = db
        self.parser = CodeRefParser()

    def render_article(self, article_id: int, sync_code: bool = False) -> Dict:
        """
        渲染文章，嵌入代码片段。

        渲染策略：
        1. 解析文章中的所有代码引用
        2. 对每个引用，优先从 CodeReference 取缓存内容
        3. 如果 CodeReference 没有缓存，实时从 LocalCodeCache 取
        4. 无效引用显示错误提示
        5. 将 Markdown 中的引用替换为 HTML 代码块
        6. 整体转为 HTML
        """
        article = self.db.query(Article).filter(Article.id == article_id).first()
        if not article:
            return {"error": "Article not found"}

        # 解析引用
        refs = self.parser.parse_article(article.content)

        # 构建引用映射：原始文本 → HTML 片段
        ref_map = {}
        embedded_info = []

        for ref in refs:
            key = ref["raw_match"]

            # 从 CodeReference 取缓存数据
            db_ref = self.db.query(CodeReference).filter(
                CodeReference.article_id == article_id,
                CodeReference.repo == ref["repo"],
                CodeReference.file_path == ref["file_path"],
                CodeReference.line_start == ref["line_start"],
                CodeReference.line_end == ref["line_end"],
            ).first()

            is_outdated = False
            ref_is_valid = False
            ref_id = None
            if db_ref:
                is_outdated = not db_ref.is_valid
                ref_is_valid = db_ref.is_valid
                ref_id = db_ref.id
                if db_ref.is_valid and db_ref.current_content:
                    # 使用缓存的内容生成 HTML
                    html = self._generate_code_html(
                        db_ref.current_content, ref["line_start"],
                        ref["line_end"], is_outdated=is_outdated,
                        repo=ref["repo"], file_path=ref["file_path"],
                    )
                    ref_map[key] = html
                    embedded_info.append({
                        "ref_id": ref_id,
                        "repo": ref["repo"],
                        "file_path": ref["file_path"],
                        "line_start": ref["line_start"],
                        "line_end": ref["line_end"],
                        "is_valid": ref_is_valid,
                    })
                    continue

            # 实时从缓存文件获取
            validation = self.parser.validate_ref(
                ref["repo"], ref["file_path"],
                ref["line_start"], ref["line_end"],
                self.cache_service,
            )

            if validation["valid"]:
                html = self._generate_code_html(
                    validation["content"], ref["line_start"],
                    ref["line_end"], is_outdated=is_outdated,
                    repo=ref["repo"], file_path=ref["file_path"],
                )
            else:
                html = self._generate_error_html(validation)

            ref_map[key] = html
            embedded_info.append({
                "ref_id": ref_id,
                "repo": ref["repo"],
                "file_path": ref["file_path"],
                "line_start": ref["line_start"],
                "line_end": ref["line_end"],
                "is_valid": validation["valid"],
                "reason": validation.get("reason", ""),
                "message": validation.get("message", ""),
            })

        # 替换 Markdown 中的引用
        rendered_content = article.content
        for raw_match, html in ref_map.items():
            # 在 Markdown 中，引用通常在反引号内
            rendered_content = rendered_content.replace(
                f"`{raw_match}`", html
            )

        # 转换为 HTML
        full_html = markdown(rendered_content)

        return {
            "html": full_html,
            "embedded_codes": embedded_info,
        }

    def render_preview(self, content: str) -> Dict:
        """
        预览模式：不保存，只返回渲染结果。
        引用从缓存实时获取，不查 CodeReference 表。
        """
        refs = self.parser.parse_article(content)
        ref_map = {}
        ref_details = []

        for ref in refs:
            validation = self.parser.validate_ref(
                ref["repo"], ref["file_path"],
                ref["line_start"], ref["line_end"],
                self.cache_service,
            )

            if validation["valid"]:
                html = self._generate_code_html(
                    validation["content"], ref["line_start"],
                    ref["line_end"], repo=ref["repo"], file_path=ref["file_path"],
                )
            else:
                html = self._generate_error_html(validation)

            ref_map[ref["raw_match"]] = html
            ref_details.append({
                "repo": ref["repo"],
                "file_path": ref["file_path"],
                "line_start": ref["line_start"],
                "line_end": ref["line_end"],
                "is_valid": validation["valid"],
                "reason": validation.get("reason", ""),
                "message": validation.get("message", ""),
            })

        rendered_content = content
        for raw_match, html in ref_map.items():
            rendered_content = rendered_content.replace(f"`{raw_match}`", html)

        full_html = markdown(rendered_content)

        return {"html": full_html, "refs": ref_details}

    def _generate_code_html(self, content: str, start_line: int, end_line: int,
                            is_outdated: bool = False,
                            repo: str = "", file_path: str = "") -> str:
        """生成带行号的代码 HTML"""
        lines = content.split("\n")
        css_class = "embedded-code outdated" if is_outdated else "embedded-code"

        html_parts = [
            f'<div class="code-embed" data-repo="{repo}" data-file="{file_path}">',
        ]

        if is_outdated:
            html_parts.append(
                '<div class="outdated-banner">'
                '⚠️ 此代码引用可能已过时'
                '<button class="diff-toggle" onclick="toggleDiff(this)">查看变更</button>'
                '</div>'
            )

        html_parts.append(f'<pre><code class="{css_class}">')

        for i, line in enumerate(lines, start_line):
            html_parts.append(f'<span class="line-number">{i}</span> ')
            escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            html_parts.append(f'<span class="code-content">{escaped}</span>\n')

        html_parts.append('</code></pre>')
        html_parts.append('</div>')
        return ''.join(html_parts)

    def _generate_error_html(self, validation: Dict) -> str:
        """生成错误提示的 HTML"""
        msg = validation.get("message", "引用无效")
        return f'<div class="code-embed-error">⚠️ {msg}</div>'
```

### 5.5 ArticleValidator（文章验证器）

```python
# app/services/article_validator.py

from typing import Dict, List


class ArticleValidator:
    """文章代码引用验证器（两阶段验证）"""

    def __init__(self, cache_service: LocalCodeSyncService, db):
        self.cache_service = cache_service
        self.db = db
        self.parser = CodeRefParser()

    def validate_article(self, article_id: int, deep_check: bool = False) -> Dict:
        """
        验证单篇文章的所有代码引用。

        浅层检查（deep_check=False，默认）：
        - 文件是否缓存
        - 行号是否越界

        深层检查（deep_check=True，定时任务或手动触发）：
        - 行号越界检查
        - 内容哈希对比（检测同行号但内容已变）
        """
        article = self.db.query(Article).filter(Article.id == article_id).first()
        if not article:
            return {"error": "Article not found"}

        refs = self.parser.parse_article(article.content)
        valid_count = 0
        invalid_count = 0
        details = []

        for ref in refs:
            # 查数据库中的 CodeReference 记录
            db_ref = self.db.query(CodeReference).filter(
                CodeReference.article_id == article_id,
                CodeReference.repo == ref["repo"],
                CodeReference.file_path == ref["file_path"],
                CodeReference.line_start == ref["line_start"],
                CodeReference.line_end == ref["line_end"],
            ).first()

            # 确保 db_ref 存在（深度检查需要 content_hash）
            if not db_ref:
                db_ref = CodeReference(
                    article_id=article_id,
                    repo=ref["repo"],
                    file_path=ref["file_path"],
                    line_start=ref["line_start"],
                    line_end=ref["line_end"],
                )
                self.db.add(db_ref)
                self.db.flush()  # 获取 id 但不提交

            if deep_check:
                # 深度检查：对比 content_hash（传入统一 session）
                validation = self.parser.deep_validate(db_ref, self.db)
            else:
                # 浅层检查：行号范围
                validation = self.parser.validate_ref(
                    ref["repo"], ref["file_path"],
                    ref["line_start"], ref["line_end"],
                    self.cache_service,
                )

            db_ref.is_valid = validation["valid"]
            db_ref.last_checked_at = datetime.utcnow()
            if validation.get("content"):
                db_ref.current_content = validation["content"]
            if validation.get("diff_summary"):
                db_ref.diff_summary = validation["diff_summary"]

            if validation["valid"]:
                valid_count += 1
            else:
                invalid_count += 1

            details.append({
                "repo": ref["repo"],
                "file_path": ref["file_path"],
                "line_start": ref["line_start"],
                "line_end": ref["line_end"],
                "is_valid": validation["valid"],
                "reason": validation.get("reason", ""),
                "message": validation.get("message", ""),
                "diff_summary": validation.get("diff_summary", ""),
            })

        # 更新文章统计
        article.code_refs_count = len(refs)
        article.valid_refs_count = valid_count
        article.outdated_refs_count = invalid_count
        article.last_verified_at = datetime.utcnow()

        self.db.commit()

        return {
            "article_id": article_id,
            "validated_at": datetime.utcnow().isoformat(),
            "total_refs": len(refs),
            "valid_refs": valid_count,
            "invalid_refs": invalid_count,
            "details": details,
        }

    def batch_validate(self, deep_check: bool = False) -> Dict:
        """批量验证所有文章"""
        articles = self.db.query(Article).all()
        results = {
            "total": len(articles),
            "validated": 0,
            "with_invalid_refs": 0,
            "details": [],
        }

        for article in articles:
            result = self.validate_article(article.id, deep_check)
            results["validated"] += 1
            if result["invalid_refs"] > 0:
                results["with_invalid_refs"] += 1
                results["details"].append({
                    "article_id": article.id,
                    "title": article.title,
                    "invalid_refs": result["invalid_refs"],
                })

        return results
```

---

## 6. 关于"代码过时"的判断逻辑

### 6.1 两阶段验证

| 阶段 | 触发时机 | 检测内容 | 结果 |
|------|----------|----------|------|
| **浅层检查（行号越界）** | 每次定时同步后 | 文件是否缓存、行号是否在范围内 | valid / invalid |
| **深度检查（内容哈希）** | 定时任务（48h）或手动触发 | 引用的代码片段 SHA256 是否与保存时一致 | valid / content_changed |

### 6.2 浅层检查

```python
# 文件是否缓存
lines = cache_service.get_file_lines(repo, file_path)
if lines is None:
    return {"valid": False, "reason": "file_not_cached"}

# 行号是否越界
total_lines = len(lines)
if start_line > total_lines or end_line > total_lines:
    return {"valid": False, "reason": "line_out_of_range",
            "message": f"行号超出范围（文件当前共 {total_lines} 行）"}
```

### 6.3 深度检查

```python
# 保存引用时，存下 content_hash（引用的代码片段的 SHA256）
ref.content_hash = hashlib.sha256(snippet.encode()).hexdigest()
ref.content_snapshot = snippet  # 存原文以便后续对比

# 深度检查时，重新计算当前代码的 hash，与保存时对比
current_snippet = "\n".join(lines[start_line - 1:end_line])
current_hash = hashlib.sha256(current_snippet.encode()).hexdigest()

if current_hash != ref.content_hash:
    # 内容变了！生成 diff 摘要
    return {
        "valid": False,
        "reason": "content_changed",
        "diff_summary": unified_diff(ref.content_snapshot, current_snippet),
    }
```

### 6.4 典型场景

| 场景 | 行号检查 | 深度检查 | 显示效果 |
|------|----------|----------|----------|
| 文件没变 | ✅ valid | ✅ valid | 正常显示，绿色标记 |
| 文件新增了几行，引用的行号还在 | ✅ valid | ❌ content_changed | 代码块有红框 + ⚠️ 提示，可展开 diff |
| 文件删除了，引用的行号越界 | ❌ line_out_of_range | — | 代码块显示错误信息 |
| 引用的函数被修改了，但行号没变 | ✅ valid | ❌ content_changed | 红框 + ⚠️ 提示 + diff |

---

## 7. 前端设计

### 7.1 技术选型

| 组件 | 选择 | 理由 |
|------|------|------|
| 框架 | Alpine.js 3.x | 与现有项目一致 |
| 编辑器 | CodeMirror 6 (CDN) | 轻量、支持 Markdown 模式 |
| 代码高亮 | highlight.js (CDN) | 自动检测语言、主题统一 |
| Markdown 渲染 | marked.js (CDN) | 轻量快速 |

### 7.2 UI 页面 Mockup

文章管理功能作为一个独立的 sidebar 视图（快捷键 `6`），与现有页面切换逻辑一致。

整体交互流程：

```
┌─────────────┐   点击文章卡片    ┌─────────────┐  点击"预览"    ┌─────────────┐
│  文章列表页  │ ──────────────→  │  编辑器页    │ ────────────→ │  预览弹窗    │
│             │ ←──────────────  │             │ ←──────────── │             │
│  [新建文章]  │   保存/取消      │  CodeMirror  │  关闭预览     │  渲染后的    │
│  搜索/筛选   │                 │  元信息表单   │              │  HTML 内容   │
└─────────────┘                 └─────────────┘              └─────────────┘
```

#### 页面 A：文章列表页

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ← 学习文章                            [搜索文章…     ]  [_筛选▼_]  [＋ 新建] │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │  ┌───────────────────────────────────────────────────────────────┐  │ │
│  │  │ vLLM Engine 架构解析                         [engine] [发布]  │  │ │
│  │  │ ✓ 12/15 引用有效    最后验证: 2天前              [编辑] [×]  │  │ │
│  │  └───────────────────────────────────────────────────────────────┘  │ │
│  │  ┌───────────────────────────────────────────────────────────────┐  │ │
│  │  │ Attention Kernel 实现分析                    [kernels] [草稿]  │  │ │
│  │  │ ⚠ 3/10 引用过时    最后验证: 5天前              [编辑] [×]  │  │ │
│  │  └───────────────────────────────────────────────────────────────┘  │ │
│  │  ┌───────────────────────────────────────────────────────────────┐  │ │
│  │  │ Flash Attention 调试笔记                      [engine] [归档]  │  │ │
│  │  │ ✓ 5/5 引用全部有效    最后验证: 12天前             [编辑] [×]  │  │ │
│  │  └───────────────────────────────────────────────────────────────┘  │ │
│  │                                                                      │ │
│  │                          [← 上一页]  1/3  [下一页 →]               │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  状态: 共 12 篇文章 · 3 篇有过时引用                                    │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 页面 B：编辑器页（新建/编辑）

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ← 返回列表                                                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  标题: [vLLM Engine 架构解析_____________________________]              │
│                                                                          │
│  领域: [engine ___________________________]                              │
│                                                                          │
│  标签: [architecture] [source-code] [attention] [＋ 添加]                │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │  CodeMirror 6 — Markdown 编辑器                                    │ │
│  │  ─────────────────────────────────────────────────────────────────  │ │
│  │  1 │ # vLLM Engine 架构解析                                         │ │
│  │  2 │                                                               │ │
│  │  3 │ 本文分析 vLLM 的核心引擎调度循环。                             │ │
│  │  4 │                                                               │ │
│  │  5 │ 主循环位于 `vllm/engine/core.py:10-50`，                        │ │
│  │  6 │ 其中 `vllm/engine/core.py:15-20` 是核心逻辑。                  │ │
│  │  7 │                                                               │ │
│  │  8 │ ## 调度策略                                                    │ │
│  │  9 │                                                               │ │
│  │ 10 │ 参考 `vllm/scheduler/policy.py:80-120` 的实现。               │ │ │
│  │  └─────────────────────────────────────────────────────────────────────┤ │
│  │                                                                          │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │ │
│  │  │  工具栏: [📎 插入代码引用]  |  [👁 预览]  [💾 保存]  [✓ 验证]  │  │ │
│  │  └──────────────────────────────────────────────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ⚡ 引用状态: 7 个代码引用 (3 个未验证)                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 页面 C：预览面板（点击"预览"后弹出）

预览面板以侧边抽屉（drawer）形式打开，与现有 PR 详情抽屉一致。

```
┌─────────────────────────────────────────────────────────────────┐
│  [× 关闭预览]                                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  # vLLM Engine 架构解析                                          │
│  ───────────────────────────────────────────────────────         │
│                                                                  │
│  本文分析 vLLM 的核心引擎调度循环。                               │
│                                                                  │
│  主循环位于：                                                    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  10  def core_loop():                                       │ │
│  │  11      while True:                                        │ │
│  │  12          batch = scheduler.schedule()                   │ │
│  │  13          execute(batch)                                 │ │
│  │  14          if shutdown:                                   │ │
│  │  15              break                                      │ │
│  │  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  其中核心逻辑：                                                  │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  ⚠️ 此代码引用可能已过时                    [查看变更 ▾]     │ │
│  │  ───────────────────────────────────────────────────────     │ │
│  │  15      def schedule(self):                                 │ │
│  │  16  →      tasks = self.priority_queue.fetch()  ← 已变更   │ │
│  │  17          return tasks                                    │ │
│  │  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ## 调度策略                                                    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  ❌ 行号超出范围（文件当前共 115 行，引用行号 80-120）       │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ───────────────────────────────────────────────────────         │
│  📎 嵌入统计: 7 个代码片段 · 5 有效 · 1 过时 · 1 无效          │
└─────────────────────────────────────────────────────────────────┘
```

#### 页面 D：插入代码引用对话框

```
┌─────── 插入代码引用 ─────────────────────────────────────────────┐
│                                                                  │
│  仓库: [vllm ___________________________ ▼]                      │
│                                                                  │
│  文件: [vllm/engine/core.py]  [📂 浏览缓存文件...]                │
│                                                                  │
│  起始行: [10]                                                     │
│  结束行: [20]  (可选，留空=单行)                                  │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  预览                                                        │ │
│  │  ───────────────────────────────────────────────────────     │ │
│  │  10  def core_loop():                                       │ │
│  │  11      while True:                                        │ │
│  │  12  →     batch = scheduler.schedule()                     │ │
│  │  ...                                                         │ │
│  │  20          cleanup()                                      │ │
│  │                                                              │ │
│  │  文件共 150 行 · 引用 11 行                                  │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│                      [取消]  [✓ 确认插入]                        │
└─────────────────────────────────────────────────────────────────┘

### 7.3 文件结构

```
static/js/articles.js       — Alpine.js mixin（文章列表、编辑器、预览）
static/index.html           — 新增 sidebar 项 + 视图容器
static/css/style.css        — 新增文章相关样式
```

### 7.4 嵌入式代码显示样式

采用 GitHub 风格：深色背景、等宽字体、灰色行号、过时代码红框提示。

```css
/* 嵌入的代码片段 */
.code-embed {
    margin: 12px 0;
    border-radius: 6px;
    overflow: hidden;
}

pre code.embedded-code {
    display: block;
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 12px 16px;
    overflow-x: auto;
    font-family: 'JetBrains Mono', 'SF Mono', Consolas, monospace;
    font-size: 13px;
    line-height: 1.6;
}

pre code.embedded-code .line-number {
    color: #636e7b;
    user-select: none;
    min-width: 40px;
    display: inline-block;
    text-align: right;
    margin-right: 12px;
}

pre code.embedded-code .code-content {
    color: #e6edf3;
}

/* 过时引用 */
pre code.embedded-code.outdated {
    border-color: #ff7b72;
    background: rgba(255, 123, 114, 0.05);
}

.outdated-banner {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 12px;
    background: rgba(255, 123, 114, 0.1);
    border-bottom: 1px solid rgba(255, 123, 114, 0.3);
    color: #ff7b72;
    font-size: 13px;
    font-family: var(--font-ui);
}

.outdated-banner .diff-toggle {
    margin-left: auto;
    background: transparent;
    border: 1px solid #ff7b72;
    color: #ff7b72;
    border-radius: 4px;
    padding: 2px 8px;
    cursor: pointer;
    font-size: 12px;
}

.outdated-banner .diff-toggle:hover {
    background: rgba(255, 123, 114, 0.2);
}

/* 错误提示 */
.code-embed-error {
    background: rgba(255, 123, 114, 0.1);
    border: 1px solid #ff7b72;
    border-radius: 6px;
    padding: 12px 16px;
    color: #ff7b72;
    font-size: 14px;
}

/* 代码引用 hover 浮层 */
.code-embed:hover {
    box-shadow: 0 0 0 2px rgba(255, 180, 84, 0.2);
}

.code-embed .file-path-hint {
    display: none;
    position: absolute;
    top: -28px;
    left: 0;
    background: #1c2128;
    border: 1px solid #30363d;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
    color: #8b949e;
    white-space: nowrap;
}

.code-embed:hover .file-path-hint {
    display: block;
}
```

### 7.5 代码引用插入工具

用户点击"插入代码引用"按钮，弹出对话框：

```
┌─ 插入代码引用 ──────────────────────────────────┐
│  仓库: [vllm ▼]                                  │
│  文件: [vllm/engine/core.py]  [浏览缓存文件]      │
│  起始行: [10]                                     │
│  结束行: [20]    (可选)                           │
│                                                    │
│  预览:                                             │
│  ┌─────────────────────────────────────────────┐  │
│  │  10: def core_loop():                        │  │
│  │  11:     ...                                  │  │
│  └─────────────────────────────────────────────┘  │
│                                                    │
│  [确认插入]  [取消]                                │
└────────────────────────────────────────────────────┘
```

### 7.6 文章卡片组件

```javascript
// 文章卡片显示验证状态
<div class="article-card" @click="openArticle(article)">
    <div class="article-header">
        <h3 x-text="article.title"></h3>
        <span class="badge" :class="'status-' + article.status"></span>
    </div>
    <div class="article-meta">
        <span class="area-badge" x-text="article.area"></span>
        <span class="tags" x-text="article.tags.join(', ')"></span>
    </div>
    <div class="article-stats">
        <template x-if="article.code_refs_count > 0">
            <span class="ref-status" :class="article.outdated_refs_count > 0 ? 'warning' : 'ok'">
                <template x-if="article.outdated_refs_count > 0">
                    ⚠️ <span x-text="article.valid_refs_count + '/' + article.code_refs_count + ' 有效'"></span>
                </template>
                <template x-else>
                    ✓ <span x-text="article.code_refs_count + ' 引用全部有效'"></span>
                </template>
            </span>
            <span class="last-verified" x-text="timeAgo(article.last_verified_at)"></span>
        </template>
    </div>
</div>
```

---

## 8. 配置项

```python
# app/config.py 新增

class Config:
    # ... 现有配置 ...

    # 代码仓库列表：{"vllm": "https://github.com/vllm-project/vllm.git", ...}
    REPOS: Dict[str, str] = {}  # 从 env REPOS 解析

    # 各仓库的关注目录
    WATCH_DIRS: Dict[str, List[str]] = {}  # 从 env WATCH_DIRS_{NAME} 解析

    # 代码同步间隔（分钟）
    CODE_SYNC_INTERVAL: int = int(os.getenv("CODE_SYNC_INTERVAL", "30"))

    # 文章验证间隔（小时）
    ARTICLE_VALIDATE_INTERVAL: int = int(os.getenv("ARTICLE_VALIDATE_INTERVAL", "48"))

    @classmethod
    def get_watch_dirs(cls, repo_name: str) -> List[str]:
        """获取指定仓库的关注目录"""
        return cls.WATCH_DIRS.get(repo_name.upper(), [])

    @classmethod
    def parse_repos_config(cls) -> None:
        """从环境变量 REPOS 解析仓库配置"""
        raw = os.getenv("REPOS", "")
        if not raw:
            cls.REPOS = {}
            return

        repos = {}
        for part in raw.split(","):
            part = part.strip()
            if "=" in part:
                name, url = part.split("=", 1)
                repos[name.strip()] = url.strip()
        cls.REPOS = repos

        # 解析各仓库的 WATCH_DIRS
        for name in repos:
            env_key = f"WATCH_DIRS_{name.upper()}"
            dirs_raw = os.getenv(env_key, "")
            if dirs_raw:
                cls.WATCH_DIRS[name.upper()] = [d.strip() for d in dirs_raw.split(",") if d.strip()]
```

---

## 9. 定时任务

```python
# app/scheduler.py 新增

def sync_all_repos_job():
    """定时任务：同步所有仓库代码到缓存"""
    from app.services.repo_manager import RepoManager

    if not Config.REPOS:
        logger.warning("No REPOS configured, skipping code sync")
        return

    manager = RepoManager()
    for repo_name in Config.REPOS:
        try:
            result = manager.pull_and_sync(repo_name)
            logger.info(f"Repo {repo_name} synced: {result}")
        except Exception:
            logger.exception(f"Error syncing repo {repo_name}")


def validate_articles_job():
    """定时任务：深度验证所有文章中的代码引用"""
    from app.services.article_validator import ArticleValidator
    from app.services.local_code_sync import LocalCodeSyncService
    from app.database import SessionLocal

    if not Config.REPOS:
        return

    db = SessionLocal()
    try:
        cache_service = LocalCodeSyncService(db)
        validator = ArticleValidator(cache_service, db)
        result = validator.batch_validate(deep_check=True)
        logger.info(f"Article validation completed: {result}")
    except Exception:
        logger.exception("Error validating articles")
    finally:
        db.close()


# 在 start_scheduler 中添加
scheduler.add_job(
    sync_all_repos_job,
    trigger=IntervalTrigger(minutes=Config.CODE_SYNC_INTERVAL),
    id="sync_all_repos",
    name="Sync All Repo Code",
    replace_existing=True,
)

scheduler.add_job(
    validate_articles_job,
    trigger=IntervalTrigger(hours=Config.ARTICLE_VALIDATE_INTERVAL),
    id="validate_articles",
    name="Validate Article Code Refs",
    replace_existing=True,
)
```

---

## 10. 安全设计

### 10.1 路径遍历防护

```python
# app/services/security.py

from pathlib import Path


def get_safe_repo_path(base_path: str, repo_name: str, file_path: str) -> Path:
    """
    确保文件路径在仓库范围内，防止路径遍历攻击。

    Args:
        base_path: 仓库根目录（如 data/repos）
        repo_name: 仓库名（如 vllm）
        file_path: 用户提供的文件相对路径

    Returns:
        安全的绝对路径
    """
    base = Path(base_path).resolve()
    target = (base / repo_name / file_path).resolve()

    if not target.is_relative_to(base / repo_name):
        raise ValueError(f"Path traversal detected: {repo_name}/{file_path}")

    return target
```

### 10.2 API 安全
- 已有 `AuthMiddleware` 保护所有 API 端点
- 代码缓存接口只返回已缓存的文件，不暴露任意文件系统路径

---

## 11. 路由注册

```python
# app/main.py 修改

from app.api.articles import router as articles_router
from app.api.sync import router as sync_router

app.include_router(articles_router, prefix="/api/articles", tags=["Articles"])
app.include_router(sync_router, prefix="/api/sync", tags=["Sync"])
```

---

## 12. 实施计划

| 阶段 | 内容 | 预计工时 |
|------|------|----------|
| Phase 1 | 数据模型 + RepoManager（clone/pull） | 1 天 |
| Phase 2 | 文章 CRUD API + CodeRefParser | 1 天 |
| Phase 3 | 渲染服务（预览 + 渲染） | 1 天 |
| Phase 4 | 验证服务（两阶段：行号 + 哈希） | 0.5 天 |
| Phase 5 | 前端 Alpine.js mixin + 编辑器 + 预览 | 1.5 天 |
| Phase 6 | 定时任务集成 + 安全加固 | 0.5 天 |
| **总计** | | **5.5 天** |

### 测试策略

| 类型 | 覆盖范围 |
|------|----------|
| 单元测试 | CodeRefParser 正则匹配（多仓库）、RepoManager 同步逻辑、两阶段验证 |
| 集成测试 | API 端点、渲染流程、预览流程 |
| 手动测试 | 前端编辑器交互、代码嵌入渲染效果、过时引用显示 |

---

## 13. 未来扩展

- 支持更多代码引用格式（GitHub URL、PR 链接等）
- 代码变更自动通知（邮件/IM）
- 文章导出为 PDF/Markdown 文件
- 代码片段收藏功能
- 文章模板库（源码分析模板、调试笔记模板等）