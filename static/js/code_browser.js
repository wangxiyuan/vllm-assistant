// code_browser.js — 代码浏览器 Alpine.js mixin
// 类似 IDE 的代码浏览功能：目录树 → 文件查看 → 变更历史 → Diff/Blame

function codeBrowserMixin() {
    return {
        // ===== 导航状态 =====
        cbRepo: 'vllm',
        cbPath: '',          // 当前目录路径
        cbBreadcrumb: [],    // [{name, path}, ...] 面包屑导航

        // ===== 目录树 =====
        cbTree: { dirs: [], files: [] },
        cbTreeLoading: false,

        // ===== 文件查看 =====
        cbFile: null,        // {content, total_lines, extension, path}
        cbFileLoading: false,
        cbFileScrollTop: 0,

        // ===== 变更历史 =====
        cbHistory: [],
        cbHistoryLoading: false,
        cbHistoryOpen: false,  // 是否展开历史面板

        // ===== Diff 查看 =====
        cbDiff: null,         // {diff, commit_hash}
        cbDiffLoading: false,
        cbDiffOpen: false,

        // ===== Blame 信息 =====
        cbBlame: [],          // 逐行 blame 信息
        cbBlameLoading: false,
        cbBlameVisible: false,

        // ===== 搜索 =====
        cbSearchQuery: '',
        cbSearchResults: [],
        cbSearchLoading: false,
        cbSearchOpen: false,   // 搜索面板展开
        cbSearchMode: false,   // 是否处于搜索模式

        // ===== 可用的仓库列表 =====
        cbRepos: ['vllm'],

        // ===== 全局文件名搜索 =====
        cbFileNameQuery: '',
        cbFileNameResults: [],
        cbFileNameLoading: false,
        _cbFileNameTimer: null,

        // ===== 语法高亮 =====
        _hljsInited: false,

        // ===== 函数大纲（Python 跳转）=====
        cbOutline: [],
        cbOutlineOpen: false,

        // ===== 初始化 =====
        async initCodeBrowser() {
            // 加载可用仓库列表
            try {
                const data = await this.api('/api/code-browser/repos');
                if (data?.repos) {
                    this.cbRepos = data.repos.filter(r => r.cloned).map(r => r.name);
                }
            } catch (_) {}
            // 默认加载根目录
            await this.cbNavigateTo('');

            // 监听文件名搜索输入（防抖 300ms）
            this.$watch('cbFileNameQuery', (val) => {
                if (this._cbFileNameTimer) clearTimeout(this._cbFileNameTimer);
                const trimmed = (val || '').trim();
                if (!trimmed) {
                    this.cbFileNameResults = [];
                    this.cbFileNameLoading = false;
                    return;
                }
                this.cbFileNameLoading = true;
                this._cbFileNameTimer = setTimeout(() => {
                    this.cbDoFileNameSearch(trimmed);
                }, 300);
            });

            // 初始化目录树面板拖拽调节宽度
            this.$nextTick(() => this.cbInitResize());
        },

        // ===== 仓库切换 =====
        async cbSwitchRepo(repoName) {
            if (repoName === this.cbRepo) return;
            this.cbRepo = repoName;
            this.cbFile = null;
            this.cbHistory = [];
            this.cbSearchResults = [];
            this.cbSearchQuery = '';
            this.cbFileNameQuery = '';
            this.cbFileNameResults = [];
            await this.cbNavigateTo('');
        },

        // ===== 目录树导航（点击目录 = 进入该目录，替换当前视图） =====
        async cbNavigateTo(path) {
            this.cbPath = path;
            this.cbTreeLoading = true;
            this.cbFile = null;
            this.cbHistory = [];
            this.cbDiff = null;
            this.cbDiffOpen = false;
            this.cbSearchMode = false;
            try {
                const params = new URLSearchParams({ repo: this.cbRepo, path });
                const data = await this.api(`/api/code-browser/tree?${params}`);
                this.cbTree = data;
                // 更新面包屑
                this.cbBreadcrumb = [];
                if (path) {
                    const parts = path.split('/');
                    let acc = '';
                    for (const p of parts) {
                        acc = acc ? `${acc}/${p}` : p;
                        this.cbBreadcrumb.push({ name: p, path: acc });
                    }
                }
            } catch (e) {
                this.showToast('加载目录失败', e.message, 'error');
            } finally {
                this.cbTreeLoading = false;
            }
        },

        // 点击文件
        async cbOpenFile(filePath) {
            this.cbFile = null;
            this.cbHistory = [];
            this.cbDiff = null;
            this.cbDiffOpen = false;
            this.cbBlame = [];
            this.cbBlameVisible = false;
            this.cbFileLoading = true;
            this.cbHistoryOpen = false;
            try {
                const params = new URLSearchParams({ repo: this.cbRepo, path: filePath });
                const data = await this.api(`/api/code-browser/file?${params}`);
                this.cbFile = data;
                // 自动生成函数大纲
                this.cbOutline = this.cbBuildOutline();
                // 自动加载变更历史（等待完成再关闭 loading）
                await this.cbLoadHistory(filePath);
            } catch (e) {
                this.showToast('加载文件失败', e.message, 'error');
            } finally {
                this.cbFileLoading = false;
            }
        },

        // 加载变更历史
        async cbLoadHistory(filePath) {
            this.cbHistoryLoading = true;
            try {
                const params = new URLSearchParams({ repo: this.cbRepo, path: filePath });
                const data = await this.api(`/api/code-browser/file-history?${params}`);
                this.cbHistory = data.commits || [];
            } catch (e) {
                this.cbHistory = [];
            } finally {
                this.cbHistoryLoading = false;
            }
        },

        // ===== Diff 查看 =====
        async cbShowDiff(commit) {
            this.cbDiff = null;
            this.cbDiffLoading = true;
            this.cbDiffOpen = true;
            try {
                const params = new URLSearchParams({
                    repo: this.cbRepo,
                    path: this.cbFile.path,
                    commit_hash: commit.hash,
                });
                const data = await this.api(`/api/code-browser/commit-diff?${params}`);
                this.cbDiff = data;
            } catch (e) {
                this.showToast('加载 diff 失败', e.message, 'error');
                this.cbDiffOpen = false;
            } finally {
                this.cbDiffLoading = false;
            }
        },

        cbCloseDiff() {
            this.cbDiffOpen = false;
            this.cbDiff = null;
        },

        // 渲染 diff
        cbRenderDiff() {
            if (!this.cbDiff?.diff) return '';
            const lines = this.cbDiff.diff.split('\n');
            let html = '';
            for (const line of lines) {
                if (line.startsWith('+') && !line.startsWith('+++')) {
                    html += `<div class="diff-line diff-add">${this._escapeHtml(line)}</div>`;
                } else if (line.startsWith('-') && !line.startsWith('---')) {
                    html += `<div class="diff-line diff-del">${this._escapeHtml(line)}</div>`;
                } else if (line.startsWith('@@')) {
                    html += `<div class="diff-line diff-hunk">${this._escapeHtml(line)}</div>`;
                } else {
                    html += `<div class="diff-line diff-ctx">${this._escapeHtml(line)}</div>`;
                }
            }
            return html;
        },

        // ===== Blame 信息 =====
        async cbToggleBlame() {
            if (this.cbBlameVisible) {
                this.cbBlameVisible = false;
                return;
            }
            if (this.cbBlame.length > 0) {
                this.cbBlameVisible = true;
                return;
            }
            if (!this.cbFile) return;
            this.cbBlameLoading = true;
            try {
                const params = new URLSearchParams({ repo: this.cbRepo, path: this.cbFile.path });
                const data = await this.api(`/api/code-browser/blame?${params}`);
                const blameLines = data.lines || [];
                const totalLines = this.cbFile.total_lines || 0;
                if (blameLines.length < totalLines) {
                    for (let i = blameLines.length; i < totalLines; i++) {
                        blameLines.push({});
                    }
                }
                this.cbBlame = blameLines;
                this.cbBlameVisible = true;
            } catch (e) {
                this.showToast('加载 blame 失败', e.message, 'error');
            } finally {
                this.cbBlameLoading = false;
            }
        },

        cbBlameCell(lineIdx) {
            if (!this.cbBlameVisible) return '';
            const info = this.cbBlame[lineIdx];
            if (!info || !info.hash || info.hash === '0000000000000000000000000000000000000000') return '';
            const hash = info.hash.substring(0, 7);
            const author = (info.author || '').substring(0, 6);
            return `${hash} ${author}`;
        },

        cbBlameTitle(lineIdx) {
            if (!this.cbBlameVisible) return '';
            const info = this.cbBlame[lineIdx];
            if (!info || !info.hash || info.hash === '0000000000000000000000000000000000000000') return '';
            return `${info.hash.substring(0, 7)} — ${info.author || 'unknown'}\n${info.summary || ''}`;
        },

        cbBlameClick(lineIdx) {
            const info = this.cbBlame[lineIdx];
            if (!info || !info.hash || info.hash === '0000000000000000000000000000000000000000') return;
            const url = `https://github.com/vllm-project/vllm/commit/${info.hash}`;
            window.open(url, '_blank');
        },

        cbBlameShowTooltip(event, lineIdx) {
            const title = this.cbBlameTitle(lineIdx);
            if (!title) return;
            // 移除旧 tooltip
            const old = document.querySelector('.cb-blame-tooltip');
            if (old) old.remove();
            const el = document.createElement('div');
            el.className = 'cb-blame-tooltip';
            el.textContent = title;
            el.style.left = (event.clientX + 10) + 'px';
            el.style.top = (event.clientY - 10) + 'px';
            document.body.appendChild(el);
        },

        cbBlameHideTooltip() {
            const el = document.querySelector('.cb-blame-tooltip');
            if (el) el.remove();
        },

        // ===== 搜索 =====
        async cbToggleSearch() {
            this.cbSearchOpen = !this.cbSearchOpen;
            if (this.cbSearchOpen) {
                this.cbSearchMode = true;
                this.cbSearchQuery = '';
                this.cbSearchResults = [];
                this.$nextTick(() => {
                    const el = this.$el.querySelector('.cb-search-input');
                    if (el) el.focus();
                });
            } else {
                this.cbSearchMode = false;
                this.cbSearchResults = [];
                this.cbSearchQuery = '';
            }
        },

        async cbDoSearch() {
            const q = this.cbSearchQuery.trim();
            if (!q) return;
            this.cbSearchLoading = true;
            this.cbSearchResults = [];
            try {
                const params = new URLSearchParams({ repo: this.cbRepo, query: q });
                const data = await this.api(`/api/code-browser/search?${params}`);
                this.cbSearchResults = data.results || [];
                if (this.cbSearchResults.length === 0) {
                    this.showToast('搜索无结果', `"${q}" 未找到匹配`, 'info');
                }
            } catch (e) {
                this.showToast('搜索失败', e.message, 'error');
            } finally {
                this.cbSearchLoading = false;
            }
        },

        async cbSearchResultClick(result) {
            this.cbSearchOpen = false;
            this.cbSearchMode = false;
            // 导航到文件所在目录
            const parts = result.path.split('/');
            const dirPath = parts.slice(0, -1).join('/');
            await this.cbNavigateTo(dirPath);
            // 打开文件
            await this.cbOpenFile(result.path);
        },

        // ===== 全局文件名搜索 =====
        async cbDoFileNameSearch(query) {
            this.cbFileNameLoading = true;
            try {
                const params = new URLSearchParams({ repo: this.cbRepo, query });
                const data = await this.api(`/api/code-browser/file-names?${params}`);
                this.cbFileNameResults = data.results || [];
            } catch (e) {
                this.cbFileNameResults = [];
                this.showToast('文件名搜索失败', e.message, 'error');
            } finally {
                this.cbFileNameLoading = false;
            }
        },

        cbFileNameResultClick(result) {
            this.cbFileNameQuery = '';
            this.cbFileNameResults = [];
            // 导航到文件所在目录
            const parts = result.path.split('/');
            const dirPath = parts.slice(0, -1).join('/');
            this.cbNavigateTo(dirPath);
            // 打开文件
            this.cbOpenFile(result.path);
        },

        // 前端文件名快速过滤（当前目录内）
        cbFilterQuery: '',
        cbGetFilteredDirs() {
            if (!this.cbFilterQuery) return this.cbTree.dirs || [];
            const q = this.cbFilterQuery.toLowerCase();
            return (this.cbTree.dirs || []).filter(d => d.name.toLowerCase().includes(q));
        },
        cbGetFilteredFiles() {
            if (!this.cbFilterQuery) return this.cbTree.files || [];
            const q = this.cbFilterQuery.toLowerCase();
            return (this.cbTree.files || []).filter(f => f.name.toLowerCase().includes(q));
        },

        // ===== 面包屑导航 =====
        cbNavigateBreadcrumb(path) {
            this.cbNavigateTo(path);
        },

        // ===== 行号渲染 =====
        cbRenderLineNumbers() {
            if (!this.cbFile) return '';
            const total = this.cbFile.total_lines || 0;
            const offset = this.cbFile.line_offset || 1;
            let html = '';
            for (let i = offset; i <= offset + total - 1; i++) {
                html += `<span class="cb-line-num" data-lineno="${i}">${i}</span>\n`;
            }
            return html;
        },

        // ===== 函数大纲（Python 跳转）=====
        cbBuildOutline() {
            if (!this.cbFile?.content) return [];
            const ext = this.cbFile?.extension || '';
            // 只对 Python 文件生成大纲
            if (ext !== '.py') return [];
            const lines = this.cbFile.content.split('\n');
            const total = this.cbFile.total_lines || lines.length;
            const results = [];
            // 匹配 class/def/async def，记录缩进层级
            for (let i = 0; i < Math.min(lines.length, total); i++) {
                const line = lines[i];
                const m = line.match(/^(\s*)((?:async\s+)?def|class)\s+([a-zA-Z_]\w*)/);
                if (m) {
                    results.push({
                        name: m[3],
                        type: m[2].includes('class') ? 'class' : 'def',
                        line: i + 1,  // 1-based
                        indent: m[1].length,
                    });
                }
            }
            return results;
        },

        cbScrollToLine(lineNo) {
            const lineEl = document.querySelector(`[data-lineno="${lineNo}"]`);
            if (lineEl) {
                lineEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
            this.cbOutlineOpen = false;
        },

        // ===== 语法高亮 =====
        cbHighlightedContent() {
            if (!this.cbFile?.content) return '';
            const lang = this.cbFileLang(this.cbFile?.extension);
            // 使用 cbFileLines() 确保行数与行号列、blame 列一致
            const lines = this.cbFileLines();
            if (typeof hljs !== 'undefined' && lang && hljs.getLanguage(lang)) {
                try {
                    // 逐行高亮，每行独立包装，确保行高一致
                    return lines.map(line => {
                        if (!line) return '<span class="cb-code-line"> </span>';
                        const result = hljs.highlight(line, { language: lang, ignoreIllegals: true });
                        return `<span class="cb-code-line">${result.value || ' '}</span>`;
                    }).join('');
                } catch (_) {}
            }
            // 无高亮时：逐行输出
            return lines.map(line =>
                `<span class="cb-code-line">${this._escapeHtml(line) || ' '}</span>`
            ).join('');
        },

        _escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        },

        // ===== 获取文件图标 =====
        cbFileIcon(ext) {
            const icons = {
                '.py': '🗜️', '.js': '📜', '.ts': '📘', '.tsx': '⚛️',
                '.html': '🌐', '.css': '🎨', '.json': '📋', '.yaml': '📋',
                '.yml': '📋', '.md': '📝', '.txt': '📄', '.sh': '⚡',
                '.c': '⚙️', '.cpp': '⚙️', '.h': '🔧', '.hpp': '🔧',
                '.rs': '🦀', '.go': '🔵', '.java': '☕', '.sql': '🗃️',
                '.proto': '📡', '.toml': '⚙️', '.dockerfile': '🐳',
                '.kt': '🏗️', '.swift': '🕊️', '.scala': '⚗️',
                '.rb': '💎', '.php': '🐘', '.lua': '🌙',
                '.dart': '🎯', '.zig': '⚡', '.nim': '🔷',
                '.xml': '📰', '.gradle': '🏗️',
            };
            return icons[ext] || '📄';
        },

        // ===== 获取文件语言 =====
        cbFileLang(ext) {
            const map = {
                '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
                '.html': 'html', '.css': 'css', '.json': 'json',
                '.yaml': 'yaml', '.yml': 'yaml', '.md': 'markdown',
                '.sh': 'bash', '.c': 'c', '.cpp': 'cpp', '.h': 'c',
                '.hpp': 'cpp', '.rs': 'rust', '.go': 'go', '.java': 'java',
                '.sql': 'sql', '.toml': 'toml', '.dockerfile': 'dockerfile',
                '.kt': 'kotlin', '.kts': 'kotlin', '.swift': 'swift',
                '.scala': 'scala', '.rb': 'ruby', '.php': 'php',
                '.lua': 'lua', '.r': 'r', '.dart': 'dart',
                '.xml': 'xml', '.gradle': 'gradle', '.proto': 'protobuf',
            };
            return map[ext] || '';
        },

        // ===== 格式化日期 =====
        cbFormatDate(dateStr) {
            if (!dateStr) return '';
            const d = new Date(dateStr);
            if (isNaN(d)) return dateStr;
            return d.toLocaleString('zh-CN', {
                year: 'numeric', month: '2-digit', day: '2-digit',
                hour: '2-digit', minute: '2-digit',
            });
        },

        cbFormatRelativeDate(dateStr) {
            if (!dateStr) return '';
            const d = new Date(dateStr);
            if (isNaN(d)) return dateStr;
            const now = new Date();
            const diffMs = now - d;
            const diffMin = Math.floor(diffMs / 60000);
            if (diffMin < 1) return '刚刚';
            if (diffMin < 60) return `${diffMin} 分钟前`;
            const diffHour = Math.floor(diffMin / 60);
            if (diffHour < 24) return `${diffHour} 小时前`;
            const diffDay = Math.floor(diffHour / 24);
            if (diffDay < 7) return `${diffDay} 天前`;
            return this.cbFormatDate(dateStr);
        },

        // ===== 格式化文件大小 =====
        cbFormatSize(bytes) {
            if (bytes === undefined || bytes === null) return '';
            if (bytes < 1024) return `${bytes} B`;
            if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
            return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
        },

        // ===== 切换历史面板展开/折叠 =====
        cbToggleHistory() {
            this.cbHistoryOpen = !this.cbHistoryOpen;
        },

        // ===== 获取文件内容的显示行 =====
        cbFileLines() {
            if (!this.cbFile?.content) return [];
            const lines = this.cbFile.content.split('\n');
            // 与后端 total_lines 保持一致：如果 total_lines 比 lines 少1，说明末尾空行不算
            const total = this.cbFile.total_lines || lines.length;
            return lines.slice(0, total);
        },

        // ===== 目录树面板拖拽调节宽度 =====
        cbInitResize() {
            const handle = this.$el.querySelector('.cb-tree-resize-handle');
            if (!handle) return;
            const panel = handle.closest('.cb-tree-panel');
            if (!panel) return;

            const onStart = (e) => {
                e.preventDefault();
                const startX = e.clientX;
                const startWidth = panel.offsetWidth;

                const onMove = (ev) => {
                    const w = startWidth + (ev.clientX - startX);
                    if (w < 180) return;
                    if (w > 500) return;
                    panel.style.width = w + 'px';
                    panel.style.flex = 'none';
                };

                const onEnd = () => {
                    document.removeEventListener('mousemove', onMove);
                    document.removeEventListener('mouseup', onEnd);
                    document.body.style.cursor = '';
                    document.body.style.userSelect = '';
                };

                document.addEventListener('mousemove', onMove);
                document.addEventListener('mouseup', onEnd);
                document.body.style.cursor = 'col-resize';
                document.body.style.userSelect = 'none';
            };

            handle.addEventListener('mousedown', onStart);
        },
    };
}

window.codeBrowserMixin = codeBrowserMixin;