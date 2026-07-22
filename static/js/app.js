// app.js - 主应用状态管理 + 工具函数
// Alpine.js 根 state。包含全局导航、搜索、命令面板、toast。

function app() {
    return {
        // ===== Auth state =====
        authenticated: false,
        authToken: '',
        authError: '',

        // ===== View state =====
        currentView: 'community',
        loading: false,

        // ===== Data =====
        areas: [],
        issues: [],
        prs: [],
        myPrs: [],
        stats: { totalIssues: 0, totalPRs: 0 },

        // ===== Community filters =====
        sortBy: 'created',
        communityTab: 'prs',
        communityPage: 1,
        pageSize: 25,
        searchQuery: '',

        // ===== PR Center filters =====
        prState: 'open',
        filterConflicts: false,
        filterCIFail: false,

        // ===== 社区动态 issue 类型过滤 =====
        communityIssueType: 'all',  // 'all' / 'bug' / 'rfc' / ...
        communityIssueArea: '',  // issue 领域过滤
        communityPRArea: '',  // PR 领域过滤

        // ===== Watchlist（特别关注）=====
        watchlist: [],  // [{number, item_type, title, url, added_at}]
        watchlistSet: new Set(),  // "type:number" 快速查找
        watchlistTab: 'pr',
        // 手动添加
        manualAddType: 'issue',
        manualAddNumber: '',
        manualAddLoading: false,

        // 打开特别关注中的 PR -> 触发 PR drawer
        // watchlist 项字段是 number, openPR 期望 pr_number
        openWatchlistPR(w) {
            if (typeof this.openPR === 'function') {
                this.openPR({
                    pr_number: w.number,
                    title: w.title,
                    url: w.url,
                    state: 'open',  // 特别关注没有详细状态，先默认 open
                });
            }
        },

        // ===== Toasts =====
        toasts: [],
        toastId: 0,

        // ===== Sync state =====
        syncStatus: 'idle',
        lastSync: null,
        nextSync: null,  // ISO 字符串，来自 /api/status 的 next_run_time
        nowTick: Date.now(),  // 用于驱动倒计时 computed 重算

        // ===== Computed view meta =====
        get currentViewTitle() {
            return {
                'community': '社区动态',
                'pr-center': '我的贡献',
                'watchlist': '特别关注',
                'personal-todo': '我的任务',
                'intelligence': '洞察面板',
            }[this.currentView] || '';
        },
        get currentViewSub() {
            return '';
        },
        get searchPlaceholder() {
            const map = {
                'community': '搜索 Issues 和 PRs…',
                'pr-center': '搜索你的 PR 和 Issue…',
                'watchlist': '搜索关注项…',
                'personal-todo': '搜索任务…',
                'intelligence': '搜索报告…',
            };
            return map[this.currentView] || '搜索…';
        },
        get lastSyncAgo() {
            if (!this.lastSync) return '从未同步';
            return '同步于 ' + this.timeAgo(this.lastSync);
        },
        // 距下次同步的倒计时（如 "4 分 23 秒"）
        get nextSyncCountdown() {
            // 引用 nowTick 让 Alpine 在 tick 时重算
            void this.nowTick;
            if (!this.nextSync) return '';
            const target = new Date(this.nextSync).getTime();
            if (isNaN(target)) return '';
            const diff = target - Date.now();
            if (diff <= 0) return '即将同步';
            const totalSec = Math.floor(diff / 1000);
            const min = Math.floor(totalSec / 60);
            const sec = totalSec % 60;
            if (min > 0) return `${min} 分 ${sec} 秒后`;
            return `${sec} 秒后`;
        },
        // 侧边栏底部完整显示文本
        get syncStatusText() {
            if (this.loading) return '同步中…';
            if (this.syncStatus === 'error') return '同步失败';
            if (this.lastSync) {
                return '同步于 ' + this.exactTime(this.lastSync);
            }
            return '空闲';
        },
        // 侧边栏 tooltip（hover 显示具体时间）
        get syncStatusClass() {
            if (this.loading || this.syncStatus === 'syncing') return 'syncing';
            if (this.syncStatus === 'error') return 'error';
            return '';
        },
        get newIssuesCount() {
            return this.issues.filter(i => i.is_new).length;
        },
        get newPRsCount() {
            return this.prs.filter(p => p.is_new).length;
        },

        // ===== Search-filtered lists (computed) =====
        get filteredIssues() {
            const q = (this.searchQuery || '').toLowerCase().trim();
            let list = this.issues;
            if (this.communityIssueType !== 'all') {
                list = list.filter(i => this.issueType(i) === this.communityIssueType);
            }
            if (this.communityIssueArea) {
                list = list.filter(i => i.area === this.communityIssueArea);
            }
            if (q) {
                list = list.filter(i =>
                    (i.title || '').toLowerCase().includes(q) ||
                    String(i.number).includes(q) ||
                    (i.author || '').toLowerCase().includes(q) ||
                    (i.area || '').toLowerCase().includes(q)
                );
            }
            return list;
        },
        get filteredPRs() {
            const q = (this.searchQuery || '').toLowerCase().trim();
            let list = this.prs;
            if (this.communityPRArea) {
                list = list.filter(p => p.area === this.communityPRArea);
            }
            if (q) {
                list = list.filter(p =>
                    (p.title || '').toLowerCase().includes(q) ||
                    String(p.number).includes(q) ||
                    (p.author || '').toLowerCase().includes(q) ||
                    (p.area || '').toLowerCase().includes(q)
                );
            }
            return list;
        },
        get pagedFilteredIssues() {
            if (this.communityTab === 'prs') return [];
            const limit = this.communityPage * this.pageSize;
            return this.filteredIssues.slice(0, limit);
        },
        get pagedFilteredPRs() {
            if (this.communityTab === 'issues') return [];
            const limit = this.communityPage * this.pageSize;
            return this.filteredPRs.slice(0, limit);
        },
        get hasMoreCommunity() {
            const shown = this.pagedFilteredIssues.length + this.pagedFilteredPRs.length;
            const total = this.filteredIssues.length + this.filteredPRs.length;
            return shown < total;
        },
        get filteredWatchlist() {
            const q = (this.searchQuery || '').toLowerCase().trim();
            let list = this.watchlist;
            if (this.watchlistTab !== 'all') {
                list = list.filter(w => w.item_type === this.watchlistTab);
            }
            if (q) {
                list = list.filter(w =>
                    (w.title || '').toLowerCase().includes(q) ||
                    String(w.number).includes(q)
                );
            }
            return list;
        },

        // ===== Init =====
        async init() {
            // 尝试从 localStorage 恢复 token
            const saved = localStorage.getItem('vllm_auth_token');
            if (saved) {
                this.authToken = saved;
                // 用 /health 验证 token 是否有效
                try {
                    const res = await fetch('/health', {
                        headers: { 'Authorization': 'Bearer ' + saved },
                    });
                    if (res.ok) {
                        this.authenticated = true;
                    } else {
                        localStorage.removeItem('vllm_auth_token');
                    }
                } catch (_) {
                    localStorage.removeItem('vllm_auth_token');
                }
            }
            if (!this.authenticated) return;

            this.showLoading();
            try {
                await Promise.all([
                    this.loadAreas(),
                    this.loadCommunityData(),
                    this.loadMyPRs(),
                    this.loadMyStats(),
                    this.loadSyncStatus(),
                    this.loadWatchlist(),
                ]);
                this.lastSync = new Date().toISOString();
            } catch (e) {
                this.showToast('初始化失败', e.message || String(e), 'error');
            } finally {
                this.hideLoading();
            }
            // 每 5 分钟自动刷新数据
            setInterval(() => this.silentRefresh(), 5 * 60 * 1000);
            // 每 30 秒拉取一次下次同步时间（轻量接口）
            setInterval(() => this.loadSyncStatus(), 30 * 1000);
            // 每秒 tick 驱动倒计时重算
            setInterval(() => { this.nowTick = Date.now(); }, 1000);
        },

        // ===== 拉取 scheduler 状态（下次同步时间）=====
        async loadSyncStatus() {
            try {
                const status = await this.api('/api/status');
                if (status && status.jobs && status.jobs.length > 0) {
                    // 三个 job 同步周期一致，取最早的 next_run_time
                    const times = status.jobs
                        .map(j => j.next_run_time)
                        .filter(Boolean)
                        .sort();
                    this.nextSync = times[0] || null;
                }
            } catch (_) {
                // 静默失败，不影响主流程
            }
        },

        showLoading() { this.loading = true; },
        hideLoading() { this.loading = false; },

        // ===== Toast system =====
        showToast(title, msg = '', type = 'info', duration = 4000) {
            const id = ++this.toastId;
            this.toasts.push({id, title, msg, type});
            setTimeout(() => {
                this.toasts = this.toasts.filter(t => t.id !== id);
            }, duration);
        },

        // ===== Auth =====
        async doLogin() {
            this.authError = '';
            const token = this.authToken.trim();
            if (!token) return;
            // 用 /health 验证 token
            try {
                const res = await fetch('/health', {
                    headers: { 'Authorization': 'Bearer ' + token },
                });
                if (res.ok) {
                    localStorage.setItem('vllm_auth_token', token);
                    this.authenticated = true;
                    this.init();
                } else {
                    this.authError = '密钥无效，请重试';
                }
            } catch (_) {
                this.authError = '无法连接服务器';
            }
        },

        // ===== API helper =====
        async api(path, options = {}, timeoutMs = 90000) {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), timeoutMs);
            try {
                const headers = { 'Content-Type': 'application/json' };
                if (this.authToken) {
                    headers['Authorization'] = 'Bearer ' + this.authToken;
                }
                const res = await fetch(path, {
                    headers,
                    signal: controller.signal,
                    ...options,
                });
                if (res.status === 401) {
                    localStorage.removeItem('vllm_auth_token');
                    this.authenticated = false;
                    throw new Error('未授权，请重新登录');
                }
                if (!res.ok) {
                    let detail = res.statusText;
                    try {
                        const data = await res.json();
                        detail = data.detail || detail;
                    } catch (_) {}
                    throw new Error(detail);
                }
                return res.json();
            } catch (e) {
                if (e.name === 'AbortError') {
                    throw new Error('请求超时（90s），AI 服务可能较慢');
                }
                throw e;
            } finally {
                clearTimeout(timer);
            }
        },

        // ===== Watchlist（特别关注）=====
        _watchKey(number, type) { return type + ':' + number; },

        isWatched(number, type) {
            return this.watchlistSet.has(this._watchKey(number, type));
        },

        async loadWatchlist() {
            try {
                const items = await this.api('/api/watchlist');
                this.watchlist = items;
                this.watchlistSet = new Set(items.map(i => this._watchKey(i.number, i.item_type)));
            } catch (_) {
                // 静默失败
            }
        },

        async toggleWatch(number, type, title, url, extra) {
            const key = this._watchKey(number, type);
            if (this.watchlistSet.has(key)) {
                // 移除
                try {
                    await this.api(`/api/watchlist/${type}/${number}`, { method: 'DELETE' });
                    this.watchlistSet.delete(key);
                    this.watchlist = this.watchlist.filter(w => this._watchKey(w.number, w.item_type) !== key);
                    this.showToast('已取消关注', `#${number} 已移出特别关注`, 'info');
                } catch (e) {
                    this.showToast('取消关注失败', e.message, 'error');
                }
            } else {
                // 添加：extra 可包含 area, issue_type, state
                const meta = extra || {};
                const payload = { number, item_type: type, title, url };
                if (meta.area) payload.area = meta.area;
                if (meta.issue_type) payload.issue_type = meta.issue_type;
                if (meta.state) payload.state = meta.state;
                try {
                    await this.api('/api/watchlist', {
                        method: 'POST',
                        body: JSON.stringify(payload),
                    });
                    this.watchlistSet.add(key);
                    this.watchlist.unshift({ number, item_type: type, title, url, added_at: new Date().toISOString(), ...meta });
                    this.showToast('已加入关注', `#${number} 已加入特别关注`, 'success');
                } catch (e) {
                    this.showToast('加入关注失败', e.message, 'error');
                }
            }
        },

        // 手动添加 issue/PR 到特别关注（通过编号从 GitHub 拉取信息）
        async addWatchlistByNumber() {
            const num = parseInt(this.manualAddNumber, 10);
            if (!num || num <= 0) {
                this.showToast('编号无效', '请输入正确的 issue/PR 编号', 'error');
                return;
            }
            if (this.manualAddLoading) return;
            const type = this.manualAddType;
            const key = this._watchKey(num, type);
            if (this.watchlistSet.has(key)) {
                this.showToast('已在关注列表', `#${num} 已在特别关注中`, 'info');
                this.manualAddNumber = '';
                return;
            }
            this.manualAddLoading = true;
            try {
                const item = await this.api('/api/watchlist/add-by-number', {
                    method: 'POST',
                    body: JSON.stringify({ number: num, item_type: type }),
                }, 30000);  // GitHub API 拉取可能慢，给 30s
                this.watchlistSet.add(key);
                this.watchlist.unshift(item);
                this.showToast('已加入关注', `#${num} 已加入特别关注`, 'success');
                this.manualAddNumber = '';
                // 切换到对应 tab 显示刚添加的项
                this.watchlistTab = type;
            } catch (e) {
                this.showToast('添加失败', e.message, 'error');
            } finally {
                this.manualAddLoading = false;
            }
        },

        // ===== Time formatting =====
        timeAgo(dateStr) {
            if (!dateStr) return '';
            const date = new Date(dateStr);
            if (isNaN(date)) return '';
            const now = new Date();
            const diff = Math.floor((now - date) / 1000 / 60);
            if (diff < 1) return '刚刚';
            if (diff < 60) return `${diff} 分钟前`;
            if (diff < 24 * 60) return `${Math.floor(diff / 60)} 小时前`;
            return `${Math.floor(diff / (24 * 60))} 天前`;
        },

        // 具体本地时间（用于 hover tooltip）
        exactTime(dateStr) {
            if (!dateStr) return '';
            const d = new Date(dateStr);
            if (isNaN(d)) return '';
            return d.toLocaleString('zh-CN', {
                year: 'numeric', month: '2-digit', day: '2-digit',
                hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
            });
        },

        // ===== View switching =====
        switchView(view) {
            this.currentView = view;
            this.searchQuery = '';
            this.communityPage = 1;
            // 切到我的贡献时自动加载统计数据
            if (view === 'pr-center' && !this.myStats && !this.statsLoading) {
                this.loadMyStats();
            }
            // 切到我的任务时自动加载
            if (view === 'personal-todo') {
                this.loadTodoTasks();
            }
            // 切到洞察面板时自动加载
            if (view === 'intelligence') {
                this.loadIntelReports();
                this.loadIntelTasks();
            }
        },

        // ===== Global keyboard shortcuts =====
        handleGlobalShortcut(e) {
            // Number keys 1-6 to switch views (when not in input)
            const tag = e.target.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
            if (e.metaKey || e.ctrlKey || e.altKey) return;

            if (e.key === '1') { e.preventDefault(); this.switchView('community'); }
            else if (e.key === '2') { e.preventDefault(); this.switchView('watchlist'); }
            else if (e.key === '3') { e.preventDefault(); this.switchView('pr-center'); }
            else if (e.key === '4') { e.preventDefault(); this.switchView('personal-todo'); }
            else if (e.key === '5') { e.preventDefault(); this.switchView('intelligence'); }
            else if (e.key === 'r' || e.key === 'R') { e.preventDefault(); this.refreshAll(); }
        },

        // ===== Search input handler =====
        onSearchInput(e) {
            this.communityPage = 1;
        },

        // ===== Refresh all data =====
        async refreshAll() {
            this.syncStatus = 'syncing';
            this.showLoading();
            try {
                await this.api('/api/refresh', { method: 'POST' });
                this.showToast('已触发同步', '后台同步已启动，数据稍后将更新', 'success');
                // 等待几秒后重新加载
                setTimeout(async () => {
                    await this.silentRefresh();
                    this.lastSync = new Date().toISOString();
                    this.syncStatus = 'idle';
                    await this.loadSyncStatus();
                }, 3000);
            } catch (e) {
                this.showToast('同步失败', e.message, 'error');
                this.syncStatus = 'error';
            } finally {
                this.hideLoading();
            }
        },

        async silentRefresh() {
            try {
                await Promise.all([
                    this.loadCommunityData(),
                    this.loadMyPRs(),
                ]);
                this.lastSync = new Date().toISOString();
            } catch (_) {}
        },

        // ===== HTML escape helper =====
        esc(s) {
            if (s == null) return '';
            return String(s).replace(/[&<>"']/g, c => ({
                '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
            }[c]));
        },

        // ===== Markdown-ish renderer for AI JSON results =====
        renderAIJSON(obj) {
            if (!obj) return '';
            // 错误情况
            if (obj.error) {
                return `<p><strong class="severity-critical">错误：</strong> ${this.esc(obj.error)}</p>` +
                       (obj.raw_response ? `<pre class="ai-raw">${this.esc(obj.raw_response)}</pre>` : '');
            }
            // 只有 raw_response 没有其他解析字段
            if (obj.raw_response && Object.keys(obj).length <= 2) {
                return `<pre class="ai-raw">${this.esc(obj.raw_response)}</pre>`;
            }
            return '';
        },

        // ===== Issue title 前缀分类 =====
        // vLLM issue 常见前缀：[Bug]、[RFC]、[Feature]、[Usage]、[Installation]、[Doc] 等
        issueTypePrefix(issue) {
            const title = (issue.title || '').trim();
            const m = title.match(/^\[([^\]]+)\]/i);
            if (m) return m[1].toLowerCase();
            return null;
        },

        // 规范化的 issue 类型（合并大小写变体、同义词）
        issueType(issue) {
            const raw = this.issueTypePrefix(issue);
            if (!raw) return 'other';
            const t = raw.toLowerCase();
            // 合并常见变体
            if (['bug', 'bug报告', '缺陷'].includes(t)) return 'bug';
            if (['rfc', 'proposal', '提案'].includes(t)) return 'rfc';
            if (['feature', 'feature request', '新功能', '需求'].includes(t)) return 'feature';
            if (['usage', 'question', 'help wanted', '问答', '求助'].includes(t)) return 'usage';
            if (['installation', 'install', '安装'].includes(t)) return 'installation';
            if (['performance', 'perf'].includes(t)) return 'performance';
            if (['doc', 'docs', 'documentation', '文档'].includes(t)) return 'doc';
            if (['ci', 'build'].includes(t)) return 'ci';
            if (['refactor', 'cleanup'].includes(t)) return 'refactor';
            return t;  // 其他前缀原样返回
        },

        issueTypeLabel(type) {
            const map = {
                bug: 'Bug', rfc: 'RFC', feature: '功能', usage: '使用',
                installation: '安装', performance: '性能', doc: '文档',
                ci: 'CI', refactor: '重构', other: '其他',
            };
            return map[type] || type;
        },

        // 根据 area ID 获取中文名
        areaName(areaId) {
            if (!areaId) return '';
            const area = (this.areas || []).find(a => a.id === areaId);
            return area ? area.name : areaId;
        },
    };
}

// 正确合并多个 mixin：用 descriptors 保留 getter，避免 Object.assign 立即求值 getter 导致报错
// Object.assign 会触发 getter 求值（此时 this 不对），导致 undefined.filter 等错误，
// 让整个合并失败 -> 所有变量未定义。
// 用 defineProperty 复制 descriptor 能保留 getter，后续 Alpine 访问时才求值。
window.buildApp = function() {
    const sources = [app(), communityMixin(), prCenterMixin(), personalTodoMixin(), intelligenceMixin()];
    const result = {};
    for (const src of sources) {
        const descs = Object.getOwnPropertyDescriptors(src);
        for (const [key, desc] of Object.entries(descs)) {
            if (!(key in result)) {
                Object.defineProperty(result, key, desc);
            }
        }
    }
    return result;
};

// Global dispatch helper (legacy compat)
window.dispatchApp = function(eventName, detail) {
    window.dispatchEvent(new CustomEvent(eventName, { detail }));
};
