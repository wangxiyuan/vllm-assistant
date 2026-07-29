# 多仓库追踪设计文档

> 本文档记录了仓库管理系统的设计，包括：动态增删改、多仓库社区动态追踪。

## 第一部分：仓库缓存动态管理

### 背景

当前 git 仓库缓存通过 `.env` 中的静态 `REPOS` 环境变量控制（逗号分隔的 `name=url` 对），修改需要改 `.env` 并重启服务。改为类似用户管理的动态 CRUD 模式，通过 UI 增删改。

现有的 `RepoCache` 模型（`repo_caches` 表）已定义但未被使用——完善它并使其成为仓库数据的唯一真实来源。

### 联动资源分析

| 操作 | 联动影响 | 处理方式 |
|------|---------|---------|
| 修改 clone_url | 本地 git 目录需要重新 clone | 删除旧本地目录，重新 `git clone` 新 URL |
| 修改 branch | 本地 checkout 需要切换分支 | `git fetch && git checkout <new_branch>` |
| 删除仓库 | `LocalCodeCache` 中该 repo 的所有文件缓存 | 物理删除 |
| 删除仓库 | `CodeReference` 中该 repo 的引用（文章代码引用） | 标记 `is_valid=False` |
| 删除仓库 | `FileChangeHistory` 中该 repo 的文件变更记录 | 物理删除 |
| 删除仓库 | AI Memory 中以该 repo 为 tag 的知识条目 | 标记 `is_stale=True`（软删除） |
| 删除仓库 | 本地 `data/repos/<name>/` 克隆目录 | 物理删除 |
| 删除仓库 | `Item` 中该 repo 的 issue/PR 记录 | 物理删除（多仓库追踪阶段新增） |
| 删除仓库 | `Watchlist` 中该 repo 的记录 | 物理删除（多仓库追踪阶段新增） |

**仓库名称不可修改**：创建后不可改名。如需变更，删除重建（避免全量联动更新关联表的风险）。

### 后端改动

#### RepoCache 模型 (`app/models.py`)

- 新增 `status` 列（`active`/`deleted`，默认 `active`）
- 新增 `created_at` 和 `updated_at` DateTime 列
- 新增 `tracked` 列（Boolean，默认 False）——见第二部分
- 新增 `to_dict()` 方法

#### 数据库迁移 (`app/database.py`)

- `_ensure_repo_caches_schema()`：使用 `PRAGMA table_info` 检查列，`ALTER TABLE ADD COLUMN` 新增缺失列

#### 启动种子数据 (`app/main.py`)

- lifespan 中（`yield` 前同步执行）：检查 `repo_caches` 表是否为空，为空且 `Config.REPOS` 有数据时，将 env 中的条目写入 DB
- 然后启动异步 `_init_repo_caches()` 执行 clone

#### RepoManager (`app/services/repo_manager.py`)

- `async_ensure_cloned()`: clone/pull 成功后 upsert `RepoCache`
- `pull_and_sync()`: 同步完成后更新 `last_synced_at` 和 `commit_sha`
- 新增 `delete_local_repo(repo_name)`: 删除本地目录
- 新增 `checkout_branch(repo_name, branch)`: 切换分支
- 新增 `get_active_repos()`: 查询 status='active' 的仓库

#### 替换 Config.REPOS 引用

| 文件 | 替换方式 |
|------|---------|
| `app/main.py` | `Config.REPOS` → 查询 `RepoCache WHERE status='active'` |
| `app/scheduler.py` | 同上 |
| `app/services/code_ref_parser.py` | `Config.REPOS.keys()` → DB 查询 |
| `app/services/agent_runner.py` | `Config.REPOS.keys()` → DB 查询 |

#### API 路由 (`app/api/repos.py`)

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/repos` | 列出所有活跃仓库 |
| GET | `/api/repos/{id}` | 获取单个仓库 |
| POST | `/api/repos` | 新增仓库，异步触发 clone |
| PUT | `/api/repos/{id}` | 修改 clone_url/branch |
| DELETE | `/api/repos/{id}` | 软删除，联动清理关联资源 |
| PATCH | `/api/repos/{id}/track` | 切换追踪状态，触发同步（见第二部分） |

### 前端改动

- 新增 `RepoConfig` 接口（`frontend/src/utils/types.ts`）
- 新增 `useReposStore`（`frontend/src/stores/repos.ts`），遵循 `useUsersStore` 模式
- 侧边栏添加"仓库管理"按钮（`Sidebar.vue`、`MobileSidebar.vue`）
- `App.vue` 添加仓库管理弹窗（Teleport modal），包含名称、URL、分支表单和增删改操作

---

## 第二部分：多仓库追踪

### 需求

在仓库管理中对每个仓库新增**是否追踪**属性。当仓库标记为追踪时：
- **调度器**例行同步该仓库的 issue/PR 到社区动态
- **社区动态页**增加按仓库 tab 切换
- **贡献面板**显示对应仓库的数据
- 同步时联动：`Item` 表需要 `repo` 字段，`Watchlist` 需要支持多仓库 URL

### 关键设计决策

1. **Item 表唯一约束**：从 `(type, number)` 改为 `(repo, type, number)`。SQLite 不支持 `DROP CONSTRAINT`，通过重建表实现。
2. **仓库命名规范**：`RepoCache.repo` 存储短名（如 `vllm`），`Item.repo` 存储完整 `owner/repo` 格式（如 `vllm-project/vllm`）。API 调用时从 `RepoCache` 的 `clone_url` 中提取 owner。
3. **GitHubClient 改造**：所有方法增加可选 `repo` 参数，传参时动态构建 API URL。
4. **Area 映射**：仅对主仓库做 CODEOWNERS 映射，其他仓库设 area=None。
5. **MyPR/UserIssue 表**：暂不加 repo 字段，贡献面板仍以主仓库为主。
6. **Item 表重建**：现有数据 `repo` 设为 `vllm-project/vllm`（从 `Config.GITHUB_OWNER/Config.GITHUB_REPO` 拼接）。

### 后端模型改动

#### Item 表 (`app/models.py`)

- 新增 `repo` 列：`Column(String(100), nullable=False, default="vllm-project/vllm")`
- `UniqueConstraint`：从 `("type", "number")` 改为 `("repo", "type", "number")`
- 新增 `idx_items_repo` 索引
- `to_dict()` 增加 `"repo"` 字段

#### RepoCache 表

- 新增 `tracked` 列：`Column(Boolean, default=False, nullable=False)`

#### Watchlist 表 (`app/models.py`)

- 新增 `repo` 列：`Column(String(100), default="vllm-project/vllm")`
- `UniqueConstraint`：从 `("number", "item_type")` 改为 `("repo", "number", "item_type")`
- `to_dict()` 增加 `"repo"` 字段

#### FileChangeHistory 表

- 已有 `repo` 列（默认 `"vllm"`），调度器写入时需填入正确的 repo 值

### 数据库迁移

#### Item 表重建（`_ensure_items_repo_column`）

```python
def _ensure_items_repo_column():
    """给 items 表加 repo 列并重建唯一约束"""
    with engine.connect() as conn:
        cols = {c["name"] for c in inspect(conn).get_columns("items")}
        if "repo" in cols:
            return  # 已有列，跳过

        # SQLite 不支持 DROP CONSTRAINT，重建表
        owner = Config.GITHUB_OWNER  # "vllm-project"
        repo_name = Config.GITHUB_REPO  # "vllm"
        default_repo = f"{owner}/{repo_name}"

        conn.execute(DDL("""
            CREATE TABLE items_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo VARCHAR(100) NOT NULL DEFAULT '...',
                type VARCHAR(10) NOT NULL,
                number INTEGER NOT NULL,
                -- ... 其他列 ...
                UNIQUE(repo, type, number)
            )
        """))
        conn.execute(DDL(f"""
            INSERT INTO items_new SELECT
                id, '{default_repo}' AS repo, type, number, title, body,
                state, labels, area, author, created_at, updated_at,
                comments, url, base_sha, head_sha, additions, deletions,
                changed_files, last_sync
            FROM items
        """))
        conn.execute(DDL("DROP TABLE items"))
        conn.execute(DDL("ALTER TABLE items_new RENAME TO items"))
        conn.commit()
```

注意：重建会丢失索引，需要在重建后重新创建所有索引（`_ensure_indexes` 会处理）。

#### RepoCache tracked 列

```python
ALTER TABLE repo_caches ADD COLUMN tracked BOOLEAN NOT NULL DEFAULT 0
```

#### Watchlist repo 列

Watchlist 表已有数据，需要重建约束（同上建表策略）。

### GitHubClient 多仓库支持

**方案**：所有方法增加可选 `repo: Optional[str] = None` 参数。

```python
def _make_request(self, method, endpoint, params=None, repo=None, **kwargs):
    if repo:
        # 从 RepoCache 获取 clone_url 提取 owner/repo
        # 或直接要求传入完整 "owner/repo" 格式
        base_url = f"https://api.github.com/repos/{repo}"
    else:
        base_url = self.base_url  # 默认值
    url = f"{base_url}{endpoint}"
    return self._request_with_retry(method, url, params, **kwargs)
```

受影响的方法：
- `get_issues(state, ..., repo=None)`
- `get_issue(number, repo=None)`
- `get_pulls(state, ..., repo=None)`
- `get_pull(number, repo=None)`
- `get_user_pulls(username, repo=None)`
- `get_user_issues(username, repo=None)`
- `get_pull_files(number, repo=None)`
- `get_pull_diff(number, repo=None)`
- `get_codeowners(repo=None)`
- `get_check_runs(ref, repo=None)`
- `get_commit_status(ref, repo=None)`

**`repo` 参数格式**：完整 `owner/repo`（如 `vllm-project/vllm`），从 `RepoCache.clone_url` 中提取。

### 调度器改动

#### sync_community_data()

```python
def sync_community_data():
    """遍历所有 tracked=True 的仓库，逐个同步"""
    tracked_repos = get_tracked_repos()  # 返回 [(short_name, owner/repo)]
    for short_name, full_repo in tracked_repos:
        _sync_single_repo_community(full_repo)

def _sync_single_repo_community(repo: str):
    """同步单个仓库的 issue/PR"""
    github_client = _get_github_client()
    # 翻页拉取 issues，传入 repo 参数
    issues = github_client.get_issues(state="open", ..., repo=repo)
    pulls = github_client.get_pulls(state="open", ..., repo=repo)
    # 处理每条记录时设置 Item.repo = repo
```

#### _process_single_issue / _process_single_pr_item

- 增加 `repo` 参数
- 查询时按 `(repo, type, number)` 匹配
- 写入时设置 `Item.repo = repo`

#### 知识库构建（`_build_from_items`）

**文件：** `app/services/memory_service.py`（第 488-546 行）

当前 `_build_from_items` 从 `Item` 表构建 issue/PR 知识时，`source_ref` 和 `tags` 是写死的，需要修改以支持多仓库：

| 位置 | 当前代码 | 改为 |
|------|---------|------|
| 第 523 行 `source_ref` | `f"vllm-project/vllm#{item.number}"` | `f"{item.repo}#{item.number}"` |
| 第 512 行 `tags` | `[item.type, area] + labels` | `[item.type, area, item.repo] + labels` |

**影响分析：**
- `source_ref` 是知识库条目的唯一标识。用 `item.repo` 代替写死的 `vllm-project/vllm`，不同仓库的同号 issue 不会相互覆盖。
- `tags` 增加 `item.repo`，支持按仓库过滤检索（`recall()` 的 `tags` 参数）。
- `_build_from_local_code()` 已从 `LocalCodeCache.repo` 读取，`tags` 中已包含 repo 名，**无需修改**。
- `_build_from_articles()` 和 `_build_from_model_anatomy()` 不涉及 repo，**无需修改**。

#### 其他调度任务

- `sync_areas()`：只在主仓库执行
- `sync_user_prs()`：只从主仓库同步（MyPR/UserIssue 暂不加 repo）
- `sync_file_change_history_job()`：写入时设置正确的 `repo` 值
- 暴露 `trigger_sync_for_repo(repo)` 供 toggle 追踪时调用

### API 层改动

#### Community API (`app/api/community.py`)

`GET /api/community/items` 增加 `repo` 查询参数：
```python
repo: Optional[str] = Query(None, description="按仓库过滤"),
if repo:
    q = q.filter(Item.repo == repo)
```

#### Repos API (`app/api/repos.py`)

- `RepoCreate`/`RepoUpdate` 增加 `tracked` 字段
- 新增 `PATCH /{repo_id}/track?tracked=true` 端点
  - toggle 时触发 `trigger_sync_for_repo(repo)` 异步同步
- `_cleanup_on_delete` 增加清理 `Item` 和 `Watchlist` 中该 repo 的记录

#### Watchlist API (`app/api/watchlist.py`)

- 新增/修改端点支持 `repo` 字段

### 前端改动

#### 类型 (`frontend/src/utils/types.ts`)

- `Issue`/`PR` 接口增加可选 `repo?: string`
- `RepoConfig` 接口增加 `tracked: boolean`

#### Store (`frontend/src/stores/repos.ts`)

- `repoForm` 增加 `tracked` 字段
- 新增 `toggleTrack(repo, tracked)` 方法

#### Community Store (`frontend/src/stores/community.ts`)

- 新增 `communityRepo` 状态（当前选中的仓库，'' 表示全部）
- `loadCommunityData()` 传 `repo` 参数
- `filteredIssues`/`filteredPRs` 支持 `repo` 过滤
- 新增 `trackedRepos` computed（从 reposStore 获取已追踪仓库）

#### Watchlist Store (`frontend/src/stores/watchlist.ts`)

- `_watchKey` 增加 repo 维度避免冲突
- `toggleWatch` 支持 repo 参数

#### 视图

- **CommunityView.vue**：PRs/Issues tab 下方新增仓库 tab 栏（全部仓库 + 各追踪仓库）；修复硬编码的 GitHub URL 为使用 `item.repo`
- **PRCenterView.vue**：修复硬编码的 GitHub URL
- **WatchlistView.vue**：修复硬编码的 GitHub URL
- **App.vue**：仓库管理弹窗表单增加"是否追踪"复选框；列表项增加追踪状态显示和切换按钮

### 联动处理

| 操作 | 联动范围 |
|------|---------|
| 启用追踪 | 立即触发该仓库的 issue/PR 同步（异步） |
| 关闭追踪 | 停止同步，已缓存的 items 保留 |
| 删除仓库 | 清理 `Item` 中该 repo 的记录、`Watchlist` 中该 repo 的记录 |

## 验证方案

1. **API 测试**: `curl http://localhost:9527/api/repos` 返回 DB 中的仓库列表
2. **新增仓库**: POST 一个仓库 → 检查列表中出现 → 检查 `data/repos/<name>/` 存在 git 内容
3. **追踪开关**: PATCH tracked=true → 检查调度器日志开始同步该仓库 → 社区动态出现该仓库的 issue/PR
4. **仓库 tab 切换**: 前端社区动态页 → 仓库 tab 切换 → 只显示对应仓库的数据
5. **删除仓库联动**:
   - 检查 `local_code_cache` 中该 repo 的记录被删除
   - 检查 `item` 中该 repo 的记录被删除
   - 检查 `watchlist` 中该 repo 的记录被删除
6. **调度器**: 检查日志 `sync_all_repos_job` 仅同步 status='active' 的仓库
7. **向后兼容**: 如果 `.env` 中设置了 `REPOS=vllm=...`，首次启动时自动种子到 DB

---

## 补充：审查发现的遗漏点

### 1. `_map_pr_to_area` 的 files API 没传 repo

**文件：** `app/scheduler.py:73`

```python
files = github_client.get_pull_files(pr_number)  # ❌ 没传 repo，永远从主仓库拉
```

`get_pull_files` 内部调用 `_make_request("GET", f"/pulls/{number}/files")`，`self.base_url` 固定指向主仓库。
多仓库时需改为 `github_client.get_pull_files(pr_number, repo=full_repo)`。

**影响函数：** `_process_single_pr_item`（第 169 行调用了 `_map_pr_to_area`）、`_fetch_user_pr_detail`（第 630 行也调用了 `_map_pr_to_area`）。

### 2. `sync_file_change_history_job` 写死 `repo="vllm"`

**文件：** `app/scheduler.py:991`

```python
db.add(FileChangeHistory(..., repo="vllm", ...))
```

需要写入正确的 repo 值。但 `sync_file_change_history_job` 是从 `MyPR` 表读数据的，而 `MyPR` 表目前**没有 `repo` 字段**（只存 `pr_number` + `github_id`）。

**解决路径：** 两个方案选一
- **方案 A（推荐）**：给 `MyPR` 表加 `repo` 列，调度器同步用户 PR 时写入
- **方案 B**：从 `Item` 表按 `number` 反查 `repo`（但不同仓库可能有相同 PR number，不精确）

**推荐方案 A**，因为 `MyPR` 当前仅限主仓库，后续扩展多仓库时也需要 repo 区分。

### 3. `_refresh_personal_task_refs` 的 repo 推断不够精确

**文件：** `app/scheduler.py:690`

```python
repo_path = f"vllm-project/{ref.get('repo', 'vllm')}"
```

`ref.get('repo')` 如果存在存的是短名（如 `vllm-ascend`），拼成完整 `owner/repo` 需要知道 owner。目前 `vllm-project` 是写死的，如果追踪了非 `vllm-project` 下的仓库就不对了。

**解决：** 从 `RepoCache` 表根据短名反查完整 `clone_url` 提取 owner。但鉴于 personal task 的 `related_refs` 中 `repo` 字段当前可能不存在，这个改动优先级低，可后续处理。

### 4. `/api/community/stats` 没有 repo 过滤

**文件：** `app/api/community.py:93`

`GET /api/community/stats` 返回所有仓库的聚合统计。切换仓库 tab 时，统计数字需要跟着变。

**解决：** 增加可选 `repo` 参数：
```python
repo: Optional[str] = Query(None, description="按仓库过滤统计"),
if repo:
    q = q.filter(Item.repo == repo)
```

### 5. `AreaMapper` 硬编码 vLLM 领域定义

**文件：** `app/services/area_mapper.py`

`AREA_DEFINITIONS` 和 `label_map`（如 `area/engine` → `engine`）都是 vLLM 特有的标签体系。非 vLLM 仓库的 issue/PR 无法映射 area。

**设计决策：** 非主仓库的 issue/PR 设 `area=None`，这是预期行为，**不需要改**。后续如果需要支持其他仓库的 area 映射，可以抽象出 per-repo 的 AreaMapper 工厂。

### 6. `MyPR` 表需要 `repo` 列

`MyPR` 表当前只有 `(pr_number, github_id)` 复合主键，没有 repo 信息。这会影响：
- `sync_file_change_history_job`：无法知道 PR 属于哪个仓库
- 贡献面板（PRCenter）：如果多仓库的 PR number 相同会冲突

**解决：** 给 `MyPR` 表加 `repo` 列，默认 `"vllm-project/vllm"`，复合主键改为 `(repo, pr_number, github_id)`。

### 7. `UserIssue` 表同理

`UserIssue` 表也有 `(number, github_id)` 复合主键，没有 repo。当前设计"贡献面板暂不加 repo，以主仓库为主"，但表结构上的冲突风险仍然存在。

**解决：** 暂不处理（当前设计已说明以主仓库为主），但如果未来要支持多仓库用户 issue，需要加 `repo` 列。

### 8. 触发 sync 的竞态风险

当用户通过 `PATCH /track` 启用追踪时，会触发一次同步。但如果此时 scheduler 的定时任务也在同步同一个仓库，可能会并行拉取同一 repo 的数据。

**解决：** `_sync_single_repo_community` 内部用 `(repo, "community")` 作为 job_id，避免并发。现有的 `_running_jobs` 集合支持此模式。