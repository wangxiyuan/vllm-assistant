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
        mobileMenuOpen: false,
        sidebarCollapsed: false,

        toggleSidebar() {
            this.sidebarCollapsed = !this.sidebarCollapsed;
            document.documentElement.style.setProperty('--sidebar-w', this.sidebarCollapsed ? '60px' : '248px');
        },

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
        communityLoadingMore: false,

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
        showAddWatchlistModal: false,
        // 备注编辑
        showWatchlistEditModal: false,
        editingWatchlistItem: null,
        watchlistEditNote: '',
        watchlistEditAssigneeId: null,
        watchlistEditSaving: false,
        manualAddNote: '',
        manualAddAssigneeId: null,

        // 打开特别关注中的 PR -> 触发 PR drawer
        // watchlist 项字段是 number, openPR 期望 pr_number
        openWatchlistPR(w) {
            if (typeof this.openPR === 'function') {
                this.openPR({
                    pr_number: w.number,
                    title: w.title,
                    url: w.url,
                    state: w.state || 'open',
                    watchlist_note: w.note || '',
                    watchlist_assignee_id: w.assignee_id || null,
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

        // ===== Users state =====
        users: [],
        showUserManager: false,
        userForm: { name: '', github_id: '' },
        userFormMode: 'create',  // 'create' | 'edit'
        editingUser: null,
        userSaving: false,

        // ===== Computed view meta =====
        get currentViewTitle() {
            return {
                'community': '社区动态',
                'pr-center': '贡献面板',
                'watchlist': '特别关注',
                'personal-todo': '任务面板',
                'intelligence': '洞察面板',
                'articles': '技术Blog',
                'anatomy': '模型拆解',
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
                'anatomy': '搜索算子或模型…',
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
        get filteredListEmpty() {
            if (this.communityTab === 'prs') return this.filteredPRs.length === 0;
            return this.filteredIssues.length === 0;
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
            // 先检查是否 DEBUG 模式（不校验 token）
            try {
                const healthRes = await fetch('/health');
                if (healthRes.ok) {
                    const healthData = await healthRes.json();
                    if (healthData.debug) {
                        this.authenticated = true;
                        this._startApp();
                        return;
                    }
                }
            } catch (_) {}

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
            this._startApp();
        },

        async _startApp() {
            this.showLoading();
            try {
                await Promise.all([
                    this.loadAreas(),
                    this.loadCommunityData(),
                    this.loadSyncStatus(),
                    this.loadWatchlist(),
                    this.loadUsers(),
                ]);
                // 贡献面板（PR/Issue/Stats）在用户选择责任人后按需加载
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
                // 提取 options 中的 headers/signal，防止被 ...options 覆盖安全字段
                const { headers: extraHeaders, signal: _, ...restOptions } = options;
                const res = await fetch(path, {
                    headers: { ...headers, ...extraHeaders },
                    signal: controller.signal,
                    ...restOptions,
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

        // 通过 type+number 在 watchlist 中查找完整项
        findWatchlistItem(number, type) {
            return this.watchlist.find(i => i.number === number && i.item_type === type) || null;
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

        // 手动添加 issue/PR 到特别关注（通过编号从 GitHub 拉取信息，自动推断类型）
        async addWatchlistByNumber() {
            const num = parseInt(this.manualAddNumber, 10);
            if (!num || num <= 0) {
                this.showToast('编号无效', '请输入正确的 issue/PR 编号', 'error');
                return;
            }
            if (this.manualAddLoading) return;
            // 先检查是否已在关注列表（不确定类型，两种都查）
            const prKey = this._watchKey(num, 'pr');
            const issueKey = this._watchKey(num, 'issue');
            if (this.watchlistSet.has(prKey) || this.watchlistSet.has(issueKey)) {
                this.showToast('已在关注列表', `#${num} 已在特别关注中`, 'info');
                this.manualAddNumber = '';
                return;
            }
            this.manualAddLoading = true;
            try {
                const note = this.manualAddNote.trim();
                const assignee_id = this.manualAddAssigneeId;
                const item = await this.api('/api/watchlist/add-by-number', {
                    method: 'POST',
                    body: JSON.stringify({ number: num, note, assignee_id }),
                }, 30000);  // GitHub API 拉取可能慢，给 30s
                const key = this._watchKey(item.number, item.item_type);
                this.watchlistSet.add(key);
                this.watchlist.unshift(item);
                this.showToast('已加入关注', `#${num} 已加入特别关注`, 'success');
                this.manualAddNumber = '';
                this.manualAddNote = '';
                this.manualAddAssigneeId = null;
                // 切换到对应 tab 显示刚添加的项
                this.watchlistTab = item.item_type;
            } catch (e) {
                this.showToast('添加失败', e.message, 'error');
            } finally {
                this.manualAddLoading = false;
                this.showAddWatchlistModal = false;
            }
        },

        // ===== Watchlist item editing (note + assignee) =====
        openWatchlistEditModal(w) {
            this.editingWatchlistItem = w;
            this.watchlistEditNote = w.note || '';
            this.watchlistEditAssigneeId = w.assignee_id || null;
            this.showWatchlistEditModal = true;
        },

        closeWatchlistEditModal() {
            this.showWatchlistEditModal = false;
            this.editingWatchlistItem = null;
            this.watchlistEditNote = '';
            this.watchlistEditAssigneeId = null;
        },

        async saveWatchlistItem() {
            if (!this.editingWatchlistItem) return;
            if (this.watchlistEditSaving) return;
            const w = this.editingWatchlistItem;
            const note = this.watchlistEditNote.trim();
            const assignee_id = this.watchlistEditAssigneeId;
            this.watchlistEditSaving = true;
            try {
                const updated = await this.api(`/api/watchlist/${w.item_type}/${w.number}/note`, {
                    method: 'PUT',
                    body: JSON.stringify({ note, assignee_id }),
                });
                // 更新本地数据
                w.note = updated.note;
                w.assignee_id = updated.assignee_id;
                const idx = this.watchlist.findIndex(i => i.number === w.number && i.item_type === w.item_type);
                if (idx !== -1) {
                    this.watchlist[idx].note = updated.note;
                    this.watchlist[idx].assignee_id = updated.assignee_id;
                }
                // 同步更新详情抽屉中的显示
                if (w.item_type === 'pr' && this.selectedPR?.pr_number === w.number) {
                    this.selectedPR.watchlist_note = updated.note || '';
                    this.selectedPR.watchlist_assignee_id = updated.assignee_id;
                } else if (w.item_type === 'issue' && this.selectedIssue?.number === w.number) {
                    this.selectedIssue.watchlist_note = updated.note || '';
                    this.selectedIssue.watchlist_assignee_id = updated.assignee_id;
                }
                this.showToast('关注信息已保存', '', 'success');
                this.closeWatchlistEditModal();
            } catch (e) {
                this.showToast('保存失败', e.message, 'error');
            } finally {
                this.watchlistEditSaving = false;
            }
        },

        // ===== User management =====
        async loadUsers() {
            try {
                const data = await this.api('/api/users');
                this.users = data.users || [];
            } catch (e) {
                this.showToast('加载用户失败', e.message, 'error');
            }
        },

        openUserManager() {
            this.showUserManager = true;
            this.resetUserForm();
            this.loadUsers();
        },

        closeUserManager() {
            this.showUserManager = false;
            this.resetUserForm();
        },

        resetUserForm() {
            this.userForm = { name: '', github_id: '' };
            this.userFormMode = 'create';
            this.editingUser = null;
        },

        openEditUser(user) {
            this.userFormMode = 'edit';
            this.editingUser = user;
            this.userForm = { name: user.name, github_id: user.github_id || '' };
        },

        async saveUser() {
            const name = this.userForm.name.trim();
            if (!name) { this.showToast('显示名称不能为空', '', 'error'); return; }
            // 规范化 GitHub 登录名：去空格、去前导 @、去 github.com/ 前缀
            let githubId = (this.userForm.github_id || '').trim().replace(/^@+/, '');
            githubId = githubId.replace(/^https?:\/\/github\.com\//i, '').replace(/\/.*$/, '');
            if (githubId && !/^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$/.test(githubId)) {
                this.showToast('GitHub 登录名格式不正确', '请填写 GitHub 用户名（如 octocat），不要带 @ 或网址', 'error');
                return;
            }
            if (this.userSaving) return;
            this.userSaving = true;
            const payload = { name, github_id: githubId };
            try {
                if (this.userFormMode === 'create') {
                    const user = await this.api('/api/users', {
                        method: 'POST',
                        body: JSON.stringify(payload),
                    });
                    this.users.push(user);
                    this.showToast('用户已创建', name, 'success');
                } else if (this.editingUser) {
                    const user = await this.api(`/api/users/${this.editingUser.id}`, {
                        method: 'PUT',
                        body: JSON.stringify(payload),
                    });
                    const idx = this.users.findIndex(u => u.id === user.id);
                    if (idx >= 0) this.users[idx] = user;
                    this.showToast('用户已更新', name, 'success');
                }
                this.resetUserForm();
            } catch (e) {
                this.showToast('保存失败', e.message, 'error');
            } finally {
                this.userSaving = false;
            }
        },

        async deleteUser(user) {
            if (!confirm(`确认删除用户「${user.name}」？\n删除后，已关联该用户为责任人的任务/算子/模型将显示为「未知用户」。`)) return;
            try {
                await this.api(`/api/users/${user.id}`, { method: 'DELETE' });
                this.users = this.users.filter(u => u.id !== user.id);
                if (this.editingUser && this.editingUser.id === user.id) {
                    this.resetUserForm();
                }
                this.showToast('已删除', `用户「${user.name}」已删除`, 'info');
            } catch (e) {
                this.showToast('删除失败', e.message, 'error');
            }
        },

        userName(userId) {
            if (!userId) return '';
            const user = this.users.find(u => u.id === userId);
            return user ? user.name : '(未知用户)';
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
            // 切到贡献面板时自动加载贡献数据
            if (view === 'pr-center') {
                this.loadAllContribData();
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
            // 切到技术Blog时自动加载
            if (view === 'articles') {
                this.loadArticles();
            }
            // 切到模型拆解时自动加载
            if (view === 'anatomy') {
                if (typeof this.switchAnatomyTab === 'function') {
                    this.switchAnatomyTab(this.anatomyTab || 'operators');
                }
                // 预加载模型数据以确保 badge 计数正确
                if (typeof this.loadModels === 'function') {
                    this.loadModels();
                }
            }
        },

        // ===== Global keyboard shortcuts =====
        handleGlobalShortcut(e) {
            // Number keys 1-7 to switch views (when not in input)
            const tag = e.target.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
            if (e.metaKey || e.ctrlKey || e.altKey) return;

            if (e.key === '1') { e.preventDefault(); this.switchView('community'); }
            else if (e.key === '2') { e.preventDefault(); this.switchView('watchlist'); }
            else if (e.key === '3') { e.preventDefault(); this.switchView('pr-center'); }
            else if (e.key === '4') { e.preventDefault(); this.switchView('personal-todo'); }
            else if (e.key === '5') { e.preventDefault(); this.switchView('intelligence'); }
            else if (e.key === '6') { e.preventDefault(); this.switchView('articles'); }
            else if (e.key === '7') { e.preventDefault(); this.switchView('anatomy'); }
            else if (e.key === 'r' || e.key === 'R') { e.preventDefault(); this.refreshAll(); }
        },

        // ===== Search input handler =====
        onSearchInput(e) {
            this.communityPage = 1;
        },

        // ===== Refresh all data =====
        _refreshing: false,

        async refreshAll() {
            if (this._refreshing) return;
            this._refreshing = true;
            this.syncStatus = 'syncing';
            this.showLoading();
            try {
                await this.api('/api/refresh', { method: 'POST' });
                this.showToast('已触发同步', '后台同步已启动，数据稍后将更新', 'success');
                // 等待几秒后重新加载
                setTimeout(async () => {
                    try {
                        await this.silentRefresh();
                        this.lastSync = new Date().toISOString();
                        this.syncStatus = 'idle';
                        await this.loadSyncStatus();
                    } catch (_) {
                        this.syncStatus = 'error';
                    } finally {
                        this.hideLoading();
                        this._refreshing = false;
                    }
                }, 3000);
            } catch (e) {
                this.showToast('同步失败', e.message, 'error');
                this.syncStatus = 'error';
                this.hideLoading();
                this._refreshing = false;
            }
        },

        async silentRefresh() {
            try {
                await Promise.all([
                    this.loadCommunityData(),
                ]);
                this.lastSync = new Date().toISOString();
                this.communityLoadingMore = false;
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
    const sources = [app(), communityMixin(), prCenterMixin(), personalTodoMixin(), intelligenceMixin(), articlesMixin(), modelAnatomyMixin()];
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
