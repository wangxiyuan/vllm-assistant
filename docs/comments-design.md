# 评论功能设计

## 概述

为洞察报告（IntelligenceReport）和技术博客（Article）提供评论能力，支持 Markdown 内容、编辑/删除功能。采用多态评论表设计，方便未来扩展到其他内容类型。

## 数据模型

### Comment 表

```python
class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (
        Index("idx_comments_target", "target_type", "target_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    target_type = Column(String(20), nullable=False)   # 'article' | 'report'
    target_id = Column(Integer, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # 评论者
    content = Column(Text, nullable=False)              # Markdown 原文
    rendered_html = Column(Text)                        # 渲染缓存（防 XSS 后）
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow)
```

### 设计要点

- **多态设计**：`target_type` + `target_id` 允许一条评论关联任意内容类型，扩展性好
- **平铺评论**：无 `parent_id`，不支持嵌套回复，按 `created_at` 升序排列
- **user_id 复用 users 表**：与 Article / IntelligenceReport 的作者关联机制一致
- **rendered_html**：后端渲染 Markdown 后清洗 XSS，前端直接 `v-html`，与文章渲染模式一致
- **新表无迁移**：`Base.metadata.create_all` 自动建表，无需 `_ensure_*` ALTER，生产重启即生效

## 后端 API

### 路由注册

`app/main.py` 中注册：

```python
from app.api.comments import router as comments_router
app.include_router(comments_router, prefix="/api/comments", tags=["Comments"])
```

### 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/comments?target_type=article&target_id=123` | 获取某目标的所有评论（`created_at asc`） |
| `POST` | `/api/comments` | 创建评论 |
| `PUT` | `/api/comments/{id}` | 编辑评论内容 |
| `DELETE` | `/api/comments/{id}` | 删除评论 |

### 请求/响应模型

```python
class CommentCreate(BaseModel):
    target_type: str                    # 'article' | 'report'
    target_id: int
    content: str                        # Markdown 原文，≤2000 字
    user_id: Optional[int] = None       # 评论者

class CommentUpdate(BaseModel):
    content: str
```

### 校验逻辑

- `target_type` 必须为 `article` 或 `report`
- `target_id` 在对应表中存在（查 `Article` / `IntelligenceReport`）
- `content` 非空且长度 ≤2000
- `user_id` 若提供，需存在于 `users` 表
- Markdown 渲染：使用 `markdown` 库（复用 `ArticleRenderer` 依赖），输出 HTML 后经 `bleach` 清洗（或手动转义 `<script>`/`<iframe>`），存 `rendered_html`
- 任意人可编辑/删除任意评论（内部团队信任模型，无严格身份校验）

### 级联删除

在 `delete_article`（`app/api/articles.py`）和 `delete_report`（`app/api/intelligence.py`）中显式清理：

```python
db.query(Comment).filter(
    Comment.target_type == "article",
    # 或 "report"
    Comment.target_id == article_id,    # 或 report_id
).delete()
```

## 前端

### 类型定义（`frontend/src/utils/types.ts`）

```typescript
export interface Comment {
  id: number
  target_type: 'article' | 'report'
  target_id: number
  user_id: number | null
  user_name: string | null
  content: string
  rendered_html: string
  created_at: string
  updated_at: string
}
```

### Pinia Store（`frontend/src/stores/comments.ts`）

- `comments: Ref<Comment[]>` / `loading: Ref<boolean>` / `submitting: Ref<boolean>`
- `loadComments(targetType, targetId)` → `GET /api/comments`
- `addComment(targetType, targetId, content, userId)` → `POST`，乐观追加
- `editComment(id, content)` → `PUT`
- `removeComment(id)` → `DELETE`，带 `showConfirm` 二次确认 + `showUndoToast`

### 通用组件（`frontend/src/components/common/CommentSection.vue`）

**Props**：`targetType: 'article' | 'report'`、`targetId: number`

**功能**：
- 评论列表：用户名 + 相对时间 + `v-html="rendered_html"` + 编辑/删除按钮（任意人可见）
- 输入框：Markdown 编辑，Enter 发送 / Shift+Enter 换行，字数提示
- 用户选择下拉：复用 `useUsersStore`，选过后写入 `localStorage.setItem('comment_user_id', id)`，下次挂载自动选中并显示"以 XXX 身份评论 [切换]"
- 编辑态：点击编辑后该条变 textarea + 保存/取消
- 空状态："还没有评论，来说点什么吧"

**挂载行为**：组件 `onMounted` 时 `loadComments`，`onUnmounted` 时清空

### 集成位置

1. **文章详情视图**（`ArticlesView.vue` 中 `articleViewOpen` 区块底部）
2. **报告详情模态框**（`IntelligenceView.vue` 中 `modal-body.report-content` 底部）

## 安全

- **XSS 防护**：后端 Markdown 渲染后清洗 HTML，禁用 `<script>`/`<iframe>`
- **长度限制**：`content` ≤2000 字符
- **无级联约束**：多态 FK 无法直接建约束，显式在删除内容时清理评论
- **后端不信任前端缓存**：`POST` 时仍校验 `user_id` 存在于 `users` 表

## 实现顺序

1. `app/models.py` 加 `Comment` 类
2. 新建 `app/api/comments.py` + 注册路由
3. 文章/报告删除接口加评论清理
4. `frontend/src/utils/types.ts` 加 `Comment` interface
5. 新建 `frontend/src/stores/comments.ts`
6. 新建 `frontend/src/components/common/CommentSection.vue`
7. 在 `ArticlesView.vue` 和 `IntelligenceView.vue` 嵌入组件
8. `./deploy.sh restart` 验证