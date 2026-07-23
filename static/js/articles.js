// articles.js — 学习文章管理 Alpine.js mixin
// 对应 DESIGN-ARTICLES.md 7.2 UI 页面

function articlesMixin() {
    return {
        // ===== 文章列表状态 =====
        articles: [],
        articlesLoading: false,
        articlesTotal: 0,
        articleFilterArea: '',
        articleFilterStatus: 'all',
        articleSortBy: 'updated',
        articleSortOrder: 'desc',

        // ===== 编辑器状态（全屏子视图）=====
        articleEditorOpen: false,
        articleEditorSubView: 'editor',  // 'editor' | 'preview'
        articleEditorMode: 'create',  // 'create' | 'edit'
        articleForm: {
            id: null,
            title: '',
            content: '',
            area: '',
            tags: [],
            status: 'draft',
        },
        // 脏状态追踪：表单初始内容的快照，用于检测未保存修改
        articleFormSnapshot: null,
        editorTagInput: '',

        // ===== 预览 =====
        previewHtml: '',
        previewRefs: [],

        // ===== 文章详情 =====
        articleViewOpen: false,
        selectedArticle: null,
        articleDetailLoading: false,
        articleRenderedHtml: '',
        articleEmbeddedCodes: [],

        // ===== 验证 =====
        validating: false,
        validationResult: null,
        deletingArticle: false,

        // ===== 插入代码引用对话框 =====
        showInsertRef: false,
        insertRef: {
            repo: 'vllm',
            file_path: '',
            line_start: 1,
            line_end: 10,
        },
        insertRefPreview: '',
        cacheFiles: [],

        // ===== 统计 =====
        get articleStatsText() {
            const total = this.articles.length;
            const outdated = this.articles.filter(a => a.outdated_refs_count > 0).length;
            if (total === 0) return '暂无文章';
            return `共 ${total} 篇文章 · ${outdated} 篇有过时引用`;
        },

        // ===== 文章列表 API =====
        async loadArticles() {
            this.articlesLoading = true;
            try {
                const params = new URLSearchParams();
                if (this.articleFilterArea) params.set('area', this.articleFilterArea);
                if (this.articleFilterStatus !== 'all') params.set('status', this.articleFilterStatus);
                if (this.articleSortBy) params.set('sort_by', this.articleSortBy);
                if (this.articleSortOrder) params.set('sort_order', this.articleSortOrder);
                const qs = params.toString();
                const data = await this.api(`/api/articles${qs ? '?' + qs : ''}`);
                this.articles = data.articles || [];
                this.articlesTotal = data.total || 0;
            } catch (e) {
                this.showToast('加载文章失败', e.message, 'error');
            } finally {
                this.articlesLoading = false;
            }
        },

        // ===== 脏状态检测（未保存修改）=====
        get articleFormDirty() {
            if (!this.articleFormSnapshot) return false;
            const snap = this.articleFormSnapshot;
            return snap.title !== this.articleForm.title
                || snap.content !== this.articleForm.content
                || snap.area !== this.articleForm.area
                || snap.status !== this.articleForm.status
                || JSON.stringify(snap.tags) !== JSON.stringify(this.articleForm.tags);
        },

        _takeFormSnapshot() {
            this.articleFormSnapshot = {
                title: this.articleForm.title,
                content: this.articleForm.content,
                area: this.articleForm.area,
                status: this.articleForm.status,
                tags: [...this.articleForm.tags],
            };
        },

        _confirmDiscard() {
            if (this.articleFormDirty) {
                if (!confirm('有未保存的修改，确定要放弃吗？')) return false;
            }
            return true;
        },

        // ===== 新建文章 =====
        openNewArticle() {
            if (!this._confirmDiscard()) return;
            this.articleEditorMode = 'create';
            this.articleForm = { id: null, title: '', content: '', area: '', tags: [], status: 'draft' };
            this.editorTagInput = '';
            this.articleViewOpen = false;
            this.selectedArticle = null;
            this.articleEditorOpen = true;
            this.articleEditorSubView = 'editor';
            this.previewHtml = '';
            this.previewRefs = [];
            this._takeFormSnapshot();
            this._focusEditor();
        },

        // ===== 编辑文章 =====
        openEditArticle(article) {
            if (!this._confirmDiscard()) return;
            this.articleEditorMode = 'edit';
            this.articleForm = {
                id: article.id,
                title: article.title || '',
                content: article.content || '',
                area: article.area || '',
                tags: article.tags || [],
                status: article.status || 'draft',
            };
            this.editorTagInput = '';
            this.articleViewOpen = false;
            this.selectedArticle = null;
            this.articleEditorOpen = true;
            this.articleEditorSubView = 'editor';
            this.previewHtml = '';
            this.previewRefs = [];
            this._takeFormSnapshot();
            this._focusEditor();
        },

        // ===== 编辑器初始化 =====
        cmEditor: null,
        _focusEditor() {
            setTimeout(() => {
                this.initCodeMirror();
                const el = document.getElementById('article-editor');
                if (el) el.focus();
            }, 100);
        },
        async initCodeMirror() {
            const el = document.getElementById('article-editor');
            if (!el) return;
            el.value = this.articleForm.content;
            this.cmEditor = el;
        },

        onEditorInput(e) {
            this.articleForm.content = e.target.value;
        },

        // ===== 标签管理 =====
        addEditorTag() {
            const t = this.editorTagInput.trim().toLowerCase();
            if (t && !this.articleForm.tags.includes(t)) {
                this.articleForm.tags.push(t);
            }
            this.editorTagInput = '';
        },
        removeEditorTag(tag) {
            this.articleForm.tags = this.articleForm.tags.filter(t => t !== tag);
        },

        // ===== 保存文章 =====
        async saveArticle() {
            const title = this.articleForm.title.trim();
            if (!title) {
                this.showToast('标题不能为空', '', 'error');
                return;
            }
            const content = this.articleForm.content;

            const body = {
                title,
                content,
                area: this.articleForm.area || '',
                tags: this.articleForm.tags,
                status: this.articleForm.status || 'draft',
            };

            try {
                if (this.articleEditorMode === 'create') {
                    await this.api('/api/articles', {
                        method: 'POST',
                        body: JSON.stringify(body),
                    });
                    this.showToast('文章已创建', '', 'success');
                } else {
                    await this.api(`/api/articles/${this.articleForm.id}`, {
                        method: 'PUT',
                        body: JSON.stringify(body),
                    });
                    this.showToast('文章已更新', '', 'success');
                }
                this.articleEditorOpen = false;
                this.articleEditorSubView = 'editor';
                this.articleFormSnapshot = null;
                await this.loadArticles();
            } catch (e) {
                this.showToast('保存失败', e.message, 'error');
            }
        },

        // ===== 删除文章 =====
        async deleteArticle(article) {
            if (this.deletingArticle) return;
            if (!confirm(`确定删除文章「${article.title}」？此操作不可撤销。`)) return;
            this.deletingArticle = true;
            try {
                await this.api(`/api/articles/${article.id}`, { method: 'DELETE' });
                this.showToast('文章已删除', '', 'success');
                if (this.selectedArticle && this.selectedArticle.id === article.id) {
                    this.closeArticleView();
                }
                await this.loadArticles();
            } catch (e) {
                this.showToast('删除失败', e.message, 'error');
            } finally {
                this.deletingArticle = false;
            }
        },

        // ===== 预览 =====
        async previewArticle() {
            const content = this.articleForm.content;
            if (!content.trim()) {
                this.showToast('内容为空', '', 'error');
                return;
            }
            try {
                const data = await this.api('/api/articles/preview', {
                    method: 'POST',
                    body: JSON.stringify({ content }),
                });
                this.previewHtml = data.html || '';
                this.previewRefs = data.refs || [];
                this.articleEditorSubView = 'preview';
            } catch (e) {
                this.showToast('预览失败', e.message, 'error');
            }
        },
        closePreview() {
            this.articleEditorSubView = 'editor';
            this.previewHtml = '';
            this.previewRefs = [];
        },

        // ===== 查看文章详情（渲染后）=====
        async viewArticle(article) {
            this.articleViewOpen = true;
            this.selectedArticle = article;
            this.articleDetailLoading = true;
            this.articleRenderedHtml = '';
            this.articleEmbeddedCodes = [];
            try {
                const data = await this.api(`/api/articles/${article.id}/rendered?sync_code=false`);
                this.articleRenderedHtml = data.html || '';
                this.articleEmbeddedCodes = data.embedded_codes || [];
            } catch (e) {
                this.articleRenderedHtml = `<div class="code-embed-error">加载失败: ${this.esc(e.message)}</div>`;
            } finally {
                this.articleDetailLoading = false;
            }
        },
        closeArticleView() {
            this.articleViewOpen = false;
            this.selectedArticle = null;
            this.articleRenderedHtml = '';
            this.articleEmbeddedCodes = [];
        },

        // ===== 验证文章 =====
        async validateArticle(article, deep = false) {
            this.validating = true;
            this.validationResult = null;
            try {
                const data = await this.api(`/api/articles/${article.id}/validate`, {
                    method: 'POST',
                    body: JSON.stringify({ deep_check: deep }),
                });
                this.validationResult = data;
                const msg = data.invalid_refs > 0
                    ? `${data.invalid_refs} 个引用失效`
                    : '全部引用有效 ✓';
                this.showToast('验证完成', msg, data.invalid_refs > 0 ? 'warning' : 'success');
                await this.loadArticles();
            } catch (e) {
                this.showToast('验证失败', e.message, 'error');
            } finally {
                this.validating = false;
            }
        },
        closeValidation() {
            this.validationResult = null;
        },

        // ===== 插入代码引用 =====
        openInsertRef() {
            this.showInsertRef = true;
            this.insertRef = { repo: 'vllm', file_path: '', line_start: 1, line_end: 10 };
            this.insertRefPreview = '';
            this.cacheFiles = [];
        },
        closeInsertRef() {
            this.showInsertRef = false;
        },

        get repoOptions() {
            // 从 Config.REPOS 获取，但由于前端不知道，硬编码常见选项
            return ['vllm', 'vllm-ascend'];
        },

        async searchCacheFiles() {
            // 简单实现：用户输入文件名后尝试预览
            if (!this.insertRef.file_path) return;
            this.insertRefPreview = '加载中…';
            try {
                const data = await this.api(`/api/sync/code/${encodeURIComponent(this.insertRef.file_path)}?repo=${this.insertRef.repo}`);
                const lines = (data.content || '').split('\n');
                const start = this.insertRef.line_start;
                const end = Math.min(this.insertRef.line_end || start, lines.length);
                const snippet = lines.slice(start - 1, end).join('\n');
                this.insertRefPreview = snippet || '(空)';
            } catch (e) {
                this.insertRefPreview = `未找到文件: ${e.message}`;
            }
        },

        confirmInsertRef() {
            const ref = this.insertRef;
            const lineEnd = ref.line_end || ref.line_start;
            const codeRef = `\`${ref.repo}/${ref.file_path}:${ref.line_start}-${lineEnd}\``;
            // 插入到编辑器光标位置或末尾
            const content = this.articleForm.content;
            this.articleForm.content = content + '\n' + codeRef + '\n';
            if (this.cmEditor && typeof this.cmEditor === 'object' && this.cmEditor.tagName === 'TEXTAREA') {
                this.cmEditor.value = this.articleForm.content;
            }
            this.showInsertRef = false;
            this.showToast('已插入代码引用', '', 'success');
        },

        // ===== 验证状态显示 =====
        refStatusText(article) {
            if (!article.code_refs_count) return '无引用';
            if (article.outdated_refs_count > 0) {
                return `⚠ ${article.valid_refs_count}/${article.code_refs_count} 有效`;
            }
            return `✓ ${article.code_refs_count} 引用全部有效`;
        },
        refStatusClass(article) {
            if (!article.code_refs_count) return '';
            return article.outdated_refs_count > 0 ? 'warning' : 'ok';
        },

        // ===== 快捷键 =====
        handleArticleKeydown(e) {
            if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                e.preventDefault();
                this.saveArticle();
            }
            if ((e.ctrlKey || e.metaKey) && e.key === 'p') {
                e.preventDefault();
                this.previewArticle();
            }
            if (e.key === 'Escape') {
                if (this.articleEditorOpen && this.articleEditorSubView === 'preview') this.closePreview();
                else if (this.showInsertRef) this.closeInsertRef();
                else if (this.selectedArticle) this.closeArticleView();
                else if (this.articleEditorOpen && this._confirmDiscard()) { this.articleEditorOpen = false; this.articleFormSnapshot = null; }
            }
        },
    };
}

// 给标签添加 renderMarkdown 支持（复用 pr_center.js 的 renderMarkdown）
// 注册到全局
window.articlesMixin = articlesMixin;