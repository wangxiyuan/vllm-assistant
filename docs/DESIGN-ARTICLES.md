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
- 定时后台验证代码引用的有效性
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
    rendered_html = Column(Text)                         # 渲染后的 HTML（缓存）

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
    file_path = Column(String(500), nullable=False)    # 文件相对路径
    line_start = Column(Integer, nullable=False)        # 起始行号
    line_end = Column(Integer)                          # 结束行号

    # 验证状态
    last_checked_at = Column(DateTime)
    is_valid = Column(Boolean, default=True)            # 当前是否有效
    current_content = Column(Text)                      # 当前代码内容（用于渲染预览）
    diff_summary = Column(Text)                         # 变化摘要
```

### 2.3 LocalCodeCache（本地代码缓存）

```python
class LocalCodeCache(Base):
    """本地 vLLM 代码缓存"""
    __tablename__ = "local_code_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_path = Column(String(500), unique=True, nullable=False)  # 相对路径
    content = Column(Text)                               # 文件完整内容
    last_synced_at = Column(DateTime, nullable=False)
    checksum = Column(String(64))                        # SHA256 校验
    total_lines = Column(Integer)                       # 总行数
```

---

## 3. API 设计

### 3.1 文章管理

```
GET    /api/articles
POST   /api/articles
PUT    /api/articles/{article_id}
DELETE /api/articles/{article_id}
GET    /api/articles/{article_id}/rendered  # 渲染后的文章（含嵌入代码）
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

创建新文章。

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
  "created_at": "2024-01-15T08:00:00Z"
}
```

#### PUT /api/articles/{article_id}

更新文章内容。

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
  "updated_at": "2024-01-25T14:30:00Z"
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
  "html": "<h1>vLLM Engine 架构</h1><p>核心循环位于：</p><pre><code class=\"embedded-code\" data-ref-id=\"123\"><span class=\"line-number\">10: </span><span class=\"code-content\">def core_loop():</span>\n<span class=\"line-number\">11: </span><span class=\"code-content\">    ...</span></code></pre>",
  "embedded_codes": [
    {
      "ref_id": 123,
      "file_path": "vllm/engine/core.py",
      "line_start": 10,
      "line_end": 20,
      "is_valid": true,
      "total_lines": 150
    }
  ]
}
```

### 3.2 代码引用验证

```
POST   /api/articles/{article_id}/validate
POST   /api/articles/batch-validate
```

#### POST /api/articles/{article_id}/validate

验证单篇文章中的所有代码引用。

**Request Body:**
```json
{
  "force_refresh": false      // 是否强制重新同步本地代码
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
      "file_path": "vllm/engine/core.py",
      "line_start": 10,
      "line_end": 20,
      "is_valid": true,
      "current_content": "def core_loop():\n    ...",
      "message": ""
    },
    {
      "file_path": "vllm/scheduler/policy.py",
      "line_start": 45,
      "line_end": 50,
      "is_valid": false,
      "reason": "line_out_of_range",
      "expected_range": "1-42",
      "actual_range": "45-50",
      "message": "行号超出范围，文件当前共 42 行"
    }
  ]
}
```

### 3.3 本地代码缓存

```
POST   /api/sync/local-code
GET    /api/sync/status
```

#### POST /api/sync/local-code

手动触发本地代码同步。

**Request Body:**
```json
{
  "watch_dirs": ["vllm/engine", "vllm/scheduler"],  // 可选，默认使用配置的目录
  "force": false                                    // 是否强制重新扫描
}
```

**Response:**
```json
{
  "synced_at": "2024-01-25T14:40:00Z",
  "stats": {
    "created": 15,
    "updated": 8,
    "unchanged": 120,
    "errors": []
  },
  "details": [
    {"path": "vllm/engine/core.py", "status": "updated"},
    {"path": "vllm/scheduler/policy.py", "status": "unchanged"}
  ]
}
```

#### GET /api/sync/status

查看本地代码同步状态。

**Response:**
```json
{
  "last_synced_at": "2024-01-25T14:40:00Z",
  "next_sync_in_hours": 23,
  "cached_files": 143,
  "total_size_kb": 4500,
  "repo_path": "/Users/wangxiyuan/code/vllm"
}
```

### 3.4 代码片段渲染

```
GET    /api/code/{file_path:path}
POST   /api/code/embed
```

#### GET /api/code/{file_path}

获取缓存的代码文件内容（用于前端跳转预览）。

**Query Parameters:**
| 参数 | 类型 | 说明 |
|------|------|------|
| line_start | integer | 起始行号（可选） |
| line_end | integer | 结束行号（可选） |

**Response:**
```json
{
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
    {"file_path": "vllm/engine/core.py", "line_start": 10, "line_end": 20},
    {"file_path": "vllm/scheduler/policy.py", "line_start": 1, "line_end": 5}
  ]
}
```

**Response:**
```json
{
  "snippets": [
    {
      "file_path": "vllm/engine/core.py",
      "line_start": 10,
      "line_end": 20,
      "is_valid": true,
      "content": "def core_loop():\n    ...",
      "html": "<pre><code>...</code></pre>"
    },
    {
      "file_path": "vllm/scheduler/policy.py",
      "line_start": 1,
      "line_end": 5,
      "is_valid": false,
      "reason": "line_out_of_range",
      "message": "行号超出范围，文件当前共 3 行"
    }
  ]
}
```

---

## 4. 核心服务设计

### 4.1 LocalCodeSyncService（本地代码同步服务）

```python
# app/services/local_code_sync.py

import os
import hashlib
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

class LocalCodeSyncService:
    """本地 vLLM 代码缓存同步服务"""

    def __init__(self, local_repo_path: str, db: Session):
        self.repo_path = Path(local_repo_path).resolve()
        self.db = db

    def sync_file(self, relative_path: str) -> Dict:
        """同步单个文件到缓存"""
        full_path = self.repo_path / relative_path

        if not full_path.exists():
            return {"status": "not_found", "path": relative_path}

        try:
            content = full_path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(content.encode()).hexdigest()
            lines = content.split("\n")

            cached = self.db.query(LocalCodeCache).filter(
                LocalCodeCache.file_path == relative_path
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
                self.db.add(LocalCodeCache(
                    file_path=relative_path,
                    content=content,
                    checksum=checksum,
                    total_lines=len(lines),
                    last_synced_at=datetime.utcnow()
                ))
                return {"status": "created", "path": relative_path}

        except Exception as e:
            return {"status": "error", "path": relative_path, "error": str(e)}

    def sync_directory(self, watch_dir: str) -> Dict:
        """同步指定目录下的所有 Python 文件"""
        base_path = self.repo_path / watch_dir
        results = {"created": 0, "updated": 0, "unchanged": 0, "errors": []}

        if not base_path.exists():
            results["errors"].append({"path": watch_dir, "error": "Directory not found"})
            return results

        for py_file in sorted(base_path.rglob("*.py")):
            relative_path = str(py_file.relative_to(self.repo_path)).replace("\\", "/")
            result = self.sync_file(relative_path)

            if result["status"] == "created":
                results["created"] += 1
            elif result["status"] == "updated":
                results["updated"] += 1
            elif result["status"] == "error":
                results["errors"].append(result)
            else:
                results["unchanged"] += 1

        return results

    def sync_all(self, watch_dirs: Optional[List[str]] = None) -> Dict:
        """同步所有关注目录"""
        if watch_dirs is None:
            watch_dirs = Config.WATCH_DIRS

        all_results = {"created": 0, "updated": 0, "unchanged": 0, "errors": []}

        for watch_dir in watch_dirs:
            results = self.sync_directory(watch_dir)
            for key in ["created", "updated", "unchanged"]:
                all_results[key] += results[key]
            all_results["errors"].extend(results["errors"])

        self.db.commit()
        return all_results

    def get_file_content(self, relative_path: str) -> Optional[str]:
        """获取缓存的文件内容"""
        cached = self.db.query(LocalCodeCache).filter(
            LocalCodeCache.file_path == relative_path
        ).first()
        return cached.content if cached else None

    def get_file_lines(self, relative_path: str) -> Optional[List[str]]:
        """获取缓存的文件行列表"""
        cached = self.db.query(LocalCodeCache).filter(
            LocalCodeCache.file_path == relative_path
        ).first()
        if cached:
            return cached.content.split("\n")
        return None
```

### 4.2 CodeRefParser（代码引用解析器）

```python
# app/services/code_ref_parser.py

import re
from typing import List, Tuple, Dict

class CodeRefParser:
    """解析 Markdown 中的代码引用，支持多种格式"""

    # 匹配模式：vllm/engine/core.py:10-20 或 vllm/engine/core.py:10
    # 也支持 vllm/engine/core.py#L10 或 vllm/engine/core.py:L10-L20
    REF_PATTERN = re.compile(
        r'`?vllm/([^`\s]+)[:#]L?(\d+)(?:[-~]L?(\d+))?`?'
    )

    def parse_article(self, content: str) -> List[Dict]:
        """
        解析文章中的所有代码引用

        Returns:
            List of {
                "article_line": 行号,
                "file_path": 文件路径,
                "line_start": 起始行,
                "line_end": 结束行,
                "raw_match": 原始匹配文本
            }
        """
        lines = content.split('\n')
        results = []

        for i, line in enumerate(lines, 1):
            matches = self.REF_PATTERN.finditer(line)
            for match in matches:
                file_path = match.group(1)
                start_line = int(match.group(2))
                end_line = int(match.group(3)) if match.group(3) else start_line

                results.append({
                    "article_line": i,
                    "file_path": file_path,
                    "line_start": start_line,
                    "line_end": end_line,
                    "raw_match": match.group(0)
                })

        return results

    def validate_ref(
        self,
        file_path: str,
        start_line: int,
        end_line: int,
        cache_service: LocalCodeSyncService
    ) -> Dict:
        """验证单个引用是否有效"""
        lines = cache_service.get_file_lines(file_path)

        if lines is None:
            return {
                "valid": False,
                "reason": "file_not_cached",
                "message": f"文件 {file_path} 未在本地缓存中，请先执行代码同步"
            }

        total_lines = len(lines)

        if start_line > total_lines or end_line > total_lines:
            return {
                "valid": False,
                "reason": "line_out_of_range",
                "message": f"行号超出范围（文件当前共 {total_lines} 行）",
                "expected_range": f"1-{total_lines}",
                "actual_range": f"{start_line}-{end_line}"
            }

        # 提取引用的内容快照
        referenced_content = "\n".join(lines[start_line - 1:end_line])

        return {
            "valid": True,
            "reason": "ok",
            "content": referenced_content,
            "total_lines": total_lines
        }

    def get_snippet_html(
        self,
        file_path: str,
        start_line: int,
        end_line: int,
        cache_service: LocalCodeSyncService,
        show_line_numbers: bool = True
    ) -> str:
        """生成代码片段的 HTML"""
        lines = cache_service.get_file_lines(file_path)

        if lines is None:
            return '<div class="code-embed-error">文件未缓存</div>'

        total_lines = len(lines)
        if start_line > total_lines or end_line > total_lines:
            return f'<div class="code-embed-error">行号超出范围（文件共 {total_lines} 行）</div>'

        snippet_lines = lines[start_line - 1:end_line]
        html_parts = ['<pre><code class="embedded-code">']

        for i, line in enumerate(snippet_lines, start_line):
            if show_line_numbers:
                html_parts.append(f'<span class="line-number">{i}: </span>')
            # HTML 转义
            escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            html_parts.append(f'<span class="code-content">{escaped}</span>\n')

        html_parts.append('</code></pre>')
        return ''.join(html_parts)

    def update_article_refs(
        self,
        article_id: int,
        content: str,
        db: Session,
        cache_service: LocalCodeSyncService
    ) -> Dict:
        """
        更新文章的代码引用记录

        策略：增量更新
        - 删除不存在的引用
        - 新增新的引用
        - 保留并更新已有的引用
        """
        # 解析当前内容中的引用
        current_refs = self.parse_article(content)

        # 获取数据库中已有的引用
        existing_refs = db.query(CodeReference).filter(
            CodeReference.article_id == article_id
        ).all()

        # 构建现有引用的键集合
        existing_keys = {
            (r.file_path, r.line_start, r.line_end)
            for r in existing_refs
        }

        # 构建当前引用的键集合
        current_keys = {
            (r["file_path"], r["line_start"], r["line_end"])
            for r in current_refs
        }

        # 删除不再存在的引用
        to_delete = existing_keys - current_keys
        for ref in existing_refs:
            if (ref.file_path, ref.line_start, ref.line_end) in to_delete:
                db.delete(ref)

        # 新增或更新引用
        valid_count = 0
        invalid_count = 0

        for ref in current_refs:
            key = (ref["file_path"], ref["line_start"], ref["line_end"])
            existing = db.query(CodeReference).filter(
                CodeReference.article_id == article_id,
                CodeReference.file_path == ref["file_path"],
                CodeReference.line_start == ref["line_start"],
                CodeReference.line_end == ref["line_end"]
            ).first()

            validation = self.validate_ref(
                ref["file_path"],
                ref["line_start"],
                ref["line_end"],
                cache_service
            )

            if existing:
                # 更新引用状态
                existing.is_valid = validation["valid"]
                existing.last_checked_at = datetime.utcnow()
                if validation.get("content"):
                    existing.current_content = validation["content"]
            else:
                # 创建新引用
                db.add(CodeReference(
                    article_id=article_id,
                    article_line_start=ref["article_line"],
                    file_path=ref["file_path"],
                    line_start=ref["line_start"],
                    line_end=ref["line_end"],
                    is_valid=validation["valid"],
                    last_checked_at=datetime.utcnow(),
                    current_content=validation.get("content")
                ))

            if validation["valid"]:
                valid_count += 1
            else:
                invalid_count += 1

        # 更新文章统计
        article = db.query(Article).filter(Article.id == article_id).first()
        if article:
            article.code_refs_count = len(current_refs)
            article.valid_refs_count = valid_count
            article.outdated_refs_count = invalid_count
            article.last_verified_at = datetime.utcnow()

        db.commit()

        return {
            "total_refs": len(current_refs),
            "valid_refs": valid_count,
            "invalid_refs": invalid_count
        }
```

### 4.3 ArticleValidator（文章验证器）

```python
# app/services/article_validator.py

from typing import Dict, List

class ArticleValidator:
    """文章代码引用验证器"""

    def __init__(self, cache_service: LocalCodeSyncService, db: Session):
        self.cache_service = cache_service
        self.db = db
        self.parser = CodeRefParser()

    def validate_article(self, article_id: int, force_refresh: bool = False) -> Dict:
        """验证单篇文章的所有代码引用"""
        article = self.db.query(Article).filter(Article.id == article_id).first()
        if not article:
            return {"error": "Article not found"}

        # 如果需要，先同步本地代码
        if force_refresh:
            self.cache_service.sync_all()

        # 解析文章中的引用
        refs = self.parser.parse_article(article.content)

        # 验证每个引用
        valid_count = 0
        invalid_count = 0
        details = []

        for ref in refs:
            validation = self.parser.validate_ref(
                ref["file_path"],
                ref["line_start"],
                ref["line_end"],
                self.cache_service
            )

            # 更新数据库记录
            db_ref = self.db.query(CodeReference).filter(
                CodeReference.article_id == article_id,
                CodeReference.file_path == ref["file_path"],
                CodeReference.line_start == ref["line_start"],
                CodeReference.line_end == ref["line_end"]
            ).first()

            if db_ref:
                db_ref.is_valid = validation["valid"]
                db_ref.last_checked_at = datetime.utcnow()
                if validation.get("content"):
                    db_ref.current_content = validation["content"]

            if validation["valid"]:
                valid_count += 1
            else:
                invalid_count += 1

            details.append({
                "file_path": ref["file_path"],
                "line_start": ref["line_start"],
                "line_end": ref["line_end"],
                "is_valid": validation["valid"],
                "reason": validation.get("reason", ""),
                "message": validation.get("message", "")
            })

        # 更新文章统计
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
            "details": details
        }

    def batch_validate(self, force_refresh: bool = False) -> Dict:
        """批量验证所有文章"""
        articles = self.db.query(Article).all()

        results = {
            "total": len(articles),
            "validated": 0,
            "with_invalid_refs": 0,
            "details": []
        }

        for article in articles:
            result = self.validate_article(article.id, force_refresh)
            results["validated"] += 1

            if result["invalid_refs"] > 0:
                results["with_invalid_refs"] += 1
                results["details"].append({
                    "article_id": article.id,
                    "title": article.title,
                    "invalid_refs": result["invalid_refs"]
                })

        return results
```

### 4.4 ArticleRenderer（文章渲染器）

```python
# app/services/article_renderer.py

import re
from typing import Dict, List
from markdown import markdown

class ArticleRenderer:
    """渲染文章，将代码引用替换为实际代码片段"""

    def __init__(self, cache_service: LocalCodeSyncService, db: Session):
        self.cache_service = cache_service
        self.db = db
        self.parser = CodeRefParser()

    def render_article(self, article_id: int, sync_code: bool = False) -> Dict:
        """
        渲染文章，嵌入代码片段

        Args:
            article_id: 文章 ID
            sync_code: 是否先同步本地代码

        Returns:
            {
                "html": 渲染后的 HTML,
                "embedded_codes": 嵌入的代码信息列表
            }
        """
        article = self.db.query(Article).filter(Article.id == article_id).first()
        if not article:
            return {"error": "Article not found"}

        # 可选：先同步代码
        if sync_code:
            self.cache_service.sync_all()

        # 解析引用
        refs = self.parser.parse_article(article.content)

        # 构建引用映射：原始文本 -> HTML 片段
        ref_map = {}
        embedded_info = []

        for ref in refs:
            key = ref["raw_match"]

            # 尝试从缓存获取已存储的内容
            db_ref = self.db.query(CodeReference).filter(
                CodeReference.article_id == article_id,
                CodeReference.file_path == ref["file_path"],
                CodeReference.line_start == ref["line_start"],
                CodeReference.line_end == ref["line_end"]
            ).first()

            if db_ref and db_ref.is_valid and db_ref.current_content:
                # 使用缓存的内容生成 HTML
                html = self._generate_code_html(
                    db_ref.current_content,
                    ref["line_start"],
                    ref["line_end"]
                )
            else:
                # 实时从缓存文件获取
                validation = self.parser.validate_ref(
                    ref["file_path"],
                    ref["line_start"],
                    ref["line_end"],
                    self.cache_service
                )

                if validation["valid"]:
                    html = self._generate_code_html(
                        validation["content"],
                        ref["line_start"],
                        ref["line_end"]
                    )
                else:
                    # 无效引用，显示错误提示
                    html = f'<div class="code-embed-error">⚠️ {validation.get("message", "引用无效")}</div>'

            ref_map[key] = html
            embedded_info.append({
                "file_path": ref["file_path"],
                "line_start": ref["line_start"],
                "line_end": ref["line_end"],
                "is_valid": db_ref.is_valid if db_ref else validation["valid"]
            })

        # 替换 Markdown 中的引用
        rendered_content = article.content
        for raw_match, html in ref_map.items():
            # 在 Markdown 中，引用通常在反引号内
            rendered_content = rendered_content.replace(
                f"`{raw_match}`",
                html
            )

        # 转换为 HTML
        full_html = markdown(rendered_content)

        return {
            "html": full_html,
            "embedded_codes": embedded_info
        }

    def _generate_code_html(
        self,
        content: str,
        start_line: int,
        end_line: int
    ) -> str:
        """生成带行号的代码 HTML"""
        lines = content.split("\n")
        html_parts = ['<pre><code class="embedded-code">']

        for i, line in enumerate(lines, start_line):
            html_parts.append(f'<span class="line-number">{i}: </span>')
            # HTML 转义
            escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            html_parts.append(f'<span class="code-content">{escaped}</span>\n')

        html_parts.append('</code></pre>')
        return ''.join(html_parts)
```

---

## 5. 前端设计

### 5.1 技术选型

| 组件 | 选择 | 理由 |
|------|------|------|
| 框架 | Alpine.js 3.x | 与现有项目一致，无需引入新依赖 |
| 编辑器 | CodeMirror 6 (CDN) | 轻量、支持 Markdown 模式、可扩展 |
| 代码高亮 | highlight.js (CDN) | 自动检测语言、主题统一 |
| Markdown 渲染 | marked.js (CDN) | 轻量快速，与现有项目一致 |

### 5.2 视图结构

```
┌─────────────────────────────────────────────────────────────┐
│  学习文章管理系统                                              │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 文章列表                                                 │ │
│  │ ┌─────────────────────────────────────────────────────┐ │ │
│  │ │ □ vLLM Engine 架构解析          [engine] [published] │ │ │
│  │ │   ✓ 12/15 引用有效    最后验证: 2天前                │ │ │
│  │ ├─────────────────────────────────────────────────────┤ │ │
│  │ │ □ Attention Kernel 实现分析      [kernels] [draft]   │ │ │
│  │ │   ⚠ 3/10 引用过时    最后验证: 5天前                │ │ │
│  │ └─────────────────────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 文章编辑器                                               │ │
│  │ ┌─────────────────────────────────────────────────────┐ │ │
│  │ │ 标题: [____________________________________]          │ │ │
│  │ │ 领域: [engine ▼]  标签: [arch] [attention] [+]      │ │ │
│  │ ├─────────────────────────────────────────────────────┤ │ │
│  │ │ ┌─────────────────────────────────────────────────┐ │ │ │
│  │ │ │ Markdown 编辑器                                  │ │ │ │
│  │ │ │ # vLLM Engine 架构                              │ │ │ │
│  │ │ │                                                  │ │ │ │
│  │ │ │ 核心循环位于 `vllm/engine/core.py:10-50`        │ │ │ │
│  │ │ │                                                  │ │ │ │
│  │ │ └─────────────────────────────────────────────────┘ │ │ │
│  │ ├─────────────────────────────────────────────────────┤ │ │
│  │ │ [插入代码引用] [预览] [保存] [验证]                  │ │ │
│  │ └─────────────────────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 文章预览（渲染后，代码自动嵌入）                           │ │
│  │ ┌─────────────────────────────────────────────────────┐ │ │
│  │ │ <h1>vLLM Engine 架构</h1>                          │ │ │
│  │ │ <p>核心循环位于：</p>                               │ │ │
│  │ │ <pre><code class="embedded-code">                 │ │ │
│  │ │   <span class="line-number">10: </span>            │ │ │
│  │ │   <span class="code-content">def core_loop():</span>│ │ │
│  │ │   <span class="line-number">11: </span>            │ │ │
│  │ │   <span class="code-content">    ...</span>        │ │ │
│  │ │ </code></pre>                                       │ │ │
│  │ └─────────────────────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 代码引用插入工具

```javascript
// static/js/article_editor.js

// CodeMirror 初始化
let editor;
function initEditor() {
    editor = CodeMirror(document.getElementById('editor'), {
        mode: 'markdown',
        lineNumbers: true,
        theme: 'default',
        indentUnit: 2,
        tabSize: 2,
    });
}

function insertCodeRef() {
    // 弹出选择器让用户选择文件和行号
    const selectedFile = showFilePicker();
    if (!selectedFile) return;

    const startLine = prompt("起始行号:");
    const endLine = prompt("结束行号（可留空表示单行）:");

    const ref = `vllm/${selectedFile.path}:${startLine}${endLine ? '-' + endLine : ''}`;

    // 插入到编辑器当前位置
    const pos = editor.getCursor();
    editor.replaceRange(`\`${ref}\``, pos);
}

// 文件选择器 - 从本地缓存中浏览
function showFilePicker() {
    // 调用 API 获取已缓存的文件列表
    fetch('/api/sync/status')
        .then(r => r.json())
        .then(data => {
            // 显示文件树模态框
            showModal(data.cached_files);
        });
}
```

### 5.3 嵌入式代码渲染样式

```css
/* 嵌入的代码片段样式 */
pre code.embedded-code {
    display: block;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    padding: 12px 16px;
    overflow-x: auto;
    font-family: var(--font-mono);
    font-size: 13px;
    line-height: 1.6;
}

pre code.embedded-code .line-number {
    color: var(--text-tertiary);
    user-select: none;
    min-width: 40px;
    display: inline-block;
}

pre code.embedded-code .code-content {
    color: var(--text-primary);
}

/* 过时引用高亮 */
pre code.embedded-code.outdated {
    border-color: var(--signal-red);
    background: rgba(255, 80, 80, 0.05);
}

pre code.embedded-code.outdated::before {
    content: "⚠️ 此代码引用可能已过时";
    display: block;
    color: var(--signal-red);
    font-size: 12px;
    margin-bottom: 8px;
    padding-bottom: 8px;
    border-bottom: 1px dashed var(--signal-red);
}

/* 错误提示 */
.code-embed-error {
    background: rgba(255, 80, 80, 0.1);
    border: 1px solid var(--signal-red);
    border-radius: 6px;
    padding: 12px 16px;
    color: var(--signal-red);
    font-size: 14px;
}
```

### 5.4 文章卡片组件

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
                    ⚠️ <x-text article.valid_refs_count + '/' + article.code_refs_count + ' 有效'></x-text>
                </template>
                <template x-else>
                    ✓ <x-text article.code_refs_count + ' 引用全部有效'></x-text>
                </template>
            </span>
            <span class="last-verified" x-text="timeAgo(article.last_verified_at)"></span>
        </template>
    </div>
</div>
```

### 5.5 文章预览组件

```javascript
// 文章预览 - 渲染时自动嵌入代码
async function renderArticlePreview(articleId) {
    const response = await fetch(`/api/articles/${articleId}/rendered?sync_code=true`);
    const data = await response.json();

    // 直接渲染 HTML（包含嵌入的代码）
    document.getElementById('preview-container').innerHTML = data.html;

    // 显示嵌入统计
    if (data.embedded_codes && data.embedded_codes.length > 0) {
        const validCount = data.embedded_codes.filter(c => c.is_valid).length;
        const invalidCount = data.embedded_codes.length - validCount;
        showNotification(`已嵌入 ${data.embedded_codes.length} 个代码片段 (${validCount} 有效, ${invalidCount} 无效)`);
    }
}
```

---

## 6. 配置项

```python
# app/config.py 新增

class Config:
    # ... 现有配置 ...

    # 本地 vLLM 仓库路径
    LOCAL_VLLM_REPO_PATH = os.getenv("LOCAL_VLLM_REPO_PATH", "")

    # 关注的代码目录（用于同步）
    WATCH_DIRS = os.getenv(
        "WATCH_DIRS",
        "vllm/engine,vllm/model_executor,vllm/worker,vllm/scheduler,vllm/attention"
    ).split(",")

    # 代码同步间隔（小时）
    CODE_SYNC_INTERVAL = int(os.getenv("CODE_SYNC_INTERVAL", "24"))

    # 文章验证间隔（小时）
    ARTICLE_VALIDATE_INTERVAL = int(os.getenv("ARTICLE_VALIDATE_INTERVAL", "48"))
```

---

## 7. 定时任务设计

```python
# app/scheduler.py 新增

def sync_local_code_cache():
    """同步本地 vLLM 代码到缓存"""
    from app.services.local_code_sync import LocalCodeSyncService
    from app.database import SessionLocal

    if not Config.LOCAL_VLLM_REPO_PATH:
        logger.warning("LOCAL_VLLM_REPO_PATH not configured, skipping code sync")
        return

    db = SessionLocal()
    try:
        service = LocalCodeSyncService(Config.LOCAL_VLLM_REPO_PATH, db)
        result = service.sync_all()
        logger.info(f"Code sync completed: {result}")
    except Exception:
        logger.exception("Error syncing local code cache")
    finally:
        db.close()


def validate_all_articles():
    """验证所有文章中的代码引用"""
    from app.services.article_validator import ArticleValidator
    from app.services.local_code_sync import LocalCodeSyncService
    from app.database import SessionLocal

    if not Config.LOCAL_VLLM_REPO_PATH:
        logger.warning("LOCAL_VLLM_REPO_PATH not configured, skipping article validation")
        return

    db = SessionLocal()
    try:
        cache_service = LocalCodeSyncService(Config.LOCAL_VLLM_REPO_PATH, db)
        validator = ArticleValidator(cache_service, db)
        result = validator.batch_validate()
        logger.info(f"Article validation completed: {result}")
    except Exception:
        logger.exception("Error validating articles")
    finally:
        db.close()


# 在 start_scheduler 中添加
scheduler.add_job(
    sync_local_code_cache,
    trigger=IntervalTrigger(hours=Config.CODE_SYNC_INTERVAL),
    id="sync_local_code",
    name="Sync Local vLLM Code",
    replace_existing=True,
)

scheduler.add_job(
    validate_all_articles,
    trigger=IntervalTrigger(hours=Config.ARTICLE_VALIDATE_INTERVAL),
    id="validate_articles",
    name="Validate Article Code Refs",
    replace_existing=True,
)
```

---

## 8. 安全设计

### 8.1 路径遍历防护

```python
# app/services/security.py

from pathlib import Path

def get_safe_path(base_path: str, file_path: str) -> Path:
    """
    确保文件路径在仓库范围内，防止路径遍历攻击

    Args:
        base_path: 基础路径（如本地 vLLM 仓库路径）
        file_path: 用户提供的文件相对路径

    Returns:
        安全的绝对路径

    Raises:
        ValueError: 如果路径超出范围
    """
    base = Path(base_path).resolve()
    target = (base / file_path).resolve()

    if not target.is_relative_to(base):
        raise ValueError(f"Path traversal detected: {file_path}")

    return target
```

### 8.2 API 安全检查

```python
# app/api/sync.py

from fastapi import HTTPException
from app.services.security import get_safe_path

@router.post("/sync/local-code")
async def sync_local_code(request: SyncRequest):
    # 验证仓库路径
    if not Config.LOCAL_VLLM_REPO_PATH:
        raise HTTPException(status_code=400, detail="LOCAL_VLLM_REPO_PATH not configured")

    # 确保 watch_dirs 都在仓库范围内
    for watch_dir in request.watch_dirs or Config.WATCH_DIRS:
        try:
            safe_path = get_safe_path(Config.LOCAL_VLLM_REPO_PATH, watch_dir)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ... 执行同步
```

---

## 9. 路由注册

```python
# app/main.py 修改

from app.api.articles import router as articles_router
from app.api.sync import router as sync_router
from app.api.render import router as render_router

app.include_router(articles_router, prefix="/api/articles", tags=["Articles"])
app.include_router(sync_router, prefix="/api/sync", tags=["Sync"])
app.include_router(render_router, prefix="/api/render", tags=["Render"])
```

---

## 10. 实施计划

| 阶段 | 内容 | 预计工时 |
|------|------|----------|
| Phase 1 | 数据模型 + CRUD API | 1 天 |
| Phase 2 | 本地代码缓存同步服务 | 1 天 |
| Phase 3 | 代码引用解析 + 渲染服务 | 1.5 天 |
| Phase 4 | 前端编辑器 + 预览（含嵌入代码） | 1.5 天 |
| Phase 5 | 定时任务集成 + 安全加固 | 0.5 天 |
| **总计** | | **5.5 天** |

### 测试策略

| 类型 | 覆盖范围 |
|------|----------|
| 单元测试 | CodeRefParser 正则匹配、LocalCodeSyncService 同步逻辑 |
| 集成测试 | API 端点、渲染流程 |
| 手动测试 | 前端编辑器交互、代码嵌入渲染效果 |

---

## 11. 未来扩展

- 支持更多代码引用格式（GitHub URL、PR 链接等）
- 代码变更自动通知（邮件/IM）
- 文章导出为 PDF/Markdown 文件
- 代码片段收藏功能
- 文章模板库（源码分析模板、调试笔记模板等）