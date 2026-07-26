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
        // 编辑 watchlist 时关联任务（支持多选）
        watchlistEditTaskList: [],
        watchlistEditLinkTaskId: '',
        watchlistEditSelectedTasks: [],  // [{id, title, ...}]
        watchlistEditShowCreate: false,  // 是否显示创建新任务表单
        watchlistEditNewTaskTitle: '',
        watchlistEditNewTaskSource: 'self',
        watchlistEditNewTaskPriority: 'P2',
        manualAddNote: '',
        manualAddAssigneeId: null,
        // 手动添加 watchlist 时关联任务
        manualAddLinkTaskMode: 'none',  // 'none' | 'existing' | 'new'
        manualAddTaskSearchQuery: '',
        manualAddTaskSearchResults: [],
        manualAddTaskSearchLoading: false,
        manualAddTaskOpen: false,
        manualAddNewTaskTitle: '',
        manualAddNewTaskPriority: 'P2',
        manualAddNewTaskSource: 'self',
        manualAddSelectedTaskId: null,
        manualAddSelectedTaskTitle: '',

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
                    _linked_tasks: w.linked_tasks || [],
                });
            }
        },

        // ===== 关联任务弹窗 =====
        // 同步 drawer 中的 _linked_tasks（关联后立即在 drawer 中显示，无需关闭重开）
        _syncDrawerLinkedTasks(number, itemType) {
            const updated = this.findWatchlistItem(number, itemType);
            const tasks = updated?.linked_tasks || [];
            if (itemType === 'pr' && this.selectedPR?.pr_number === number) {
                this.selectedPR._linked_tasks = tasks;
            } else if (itemType === 'issue' && this.selectedIssue?.number === number) {
                this.selectedIssue._linked_tasks = tasks;
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

        // ===== Confirm dialog =====
        confirmDialog: {
            show: false,
            title: '',
            message: '',
            confirmText: '确认',
            cancelText: '取消',
            danger: false,
            resolve: null,
        },

        // 显示确认弹窗，返回 Promise<boolean>
        showConfirm(opts = {}) {
            return new Promise((resolve) => {
                this.confirmDialog = {
                    show: true,
                    title: opts.title || '确认操作',
                    message: opts.message || '',
                    confirmText: opts.confirmText || '确认',
                    cancelText: opts.cancelText || '取消',
                    danger: opts.danger || false,
                    resolve,
                };
            });
        },

        confirmOk() {
            const r = this.confirmDialog.resolve;
            if (r) r(true);
            this.confirmDialog.show = false;
        },

        confirmCancel() {
            const r = this.confirmDialog.resolve;
            if (r) r(false);
            this.confirmDialog.show = false;
        },

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
            // 统一 tick 驱动：每 30 秒检查一次，同时驱动倒计时和静默刷新
            let tickCount = 0;
            setInterval(() => {
                tickCount++;
                this.nowTick = Date.now();
                // 每 30 秒（1 tick）拉取下次同步时间
                this.loadSyncStatus();
                // 每 10 个 tick（5 分钟）静默刷新数据
                if (tickCount % 10 === 0) {
                    this.silentRefresh();
                }
            }, 30000);
            // 每秒更新 nowTick 驱动倒计时实时刷新
            setInterval(() => {
                this.nowTick = Date.now();
            }, 1000);
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

        // ===== 自动聚焦弹窗的第一个输入框 =====
        focusModalInput(selector = '.modal input:not([type="hidden"]), .modal textarea, .modal select') {
            this.$nextTick(() => {
                const el = document.querySelector(selector);
                if (el) setTimeout(() => el.focus(), 100);
            });
        },

        // ===== Toast system =====
        showToast(title, msg = '', type = 'info', duration = 4000) {
            const id = ++this.toastId;
            this.toasts.push({id, title, msg, type});
            setTimeout(() => {
                this.toasts = this.toasts.filter(t => t.id !== id);
            }, duration);
        },

        // 显示带"撤销"操作的 Toast
        showUndoToast(title, msg, undoCallback, duration = 8000) {
            const id = ++this.toastId;
            this.toasts.push({id, title, msg, type: 'undo', undo: true, undoCallback});
            const timer = setTimeout(() => {
                this.toasts = this.toasts.filter(t => t.id !== id);
            }, duration);
            // 存储 timer 以便撤销时清除
            this.toasts[this.toasts.length - 1]._timer = timer;
        },

        // 执行撤销
        executeUndo(id) {
            const toast = this.toasts.find(t => t.id === id);
            if (!toast) return;
            if (toast.undoCallback) {
                toast.undoCallback();
            }
            // 清除自动移除计时器并立即移除 toast
            if (toast._timer) clearTimeout(toast._timer);
            this.toasts = this.toasts.filter(t => t.id !== id);
            this.showToast('已撤销', '', 'success', 2000);
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
                // 提取 options 中的 headers，防止被 ...options 覆盖安全字段
                // 合并自定义 signal（如果有，通过 Promise.race 竞争）
                const { headers: extraHeaders, signal: customSignal, ...restOptions } = options;
                const signal = customSignal
                    ? anySignal([controller.signal, customSignal])
                    : controller.signal;
                const res = await fetch(path, {
                    headers: { ...headers, ...extraHeaders },
                    signal,
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
                // 移除前确认，防止误触
                const ok = await this.showConfirm({
                    title: '取消关注',
                    message: `确认将 #${number} 移出特别关注？`,
                    confirmText: '确认移出',
                    danger: true,
                });
                if (!ok) return;
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

                // 如果选择了关联任务，执行关联
                if (this.manualAddLinkTaskMode === 'existing' && this.manualAddSelectedTaskId) {
                    await this.api('/api/personal-todo/link-to-watchlist', {
                        method: 'POST',
                        body: JSON.stringify({
                            watchlist_item_type: item.item_type,
                            watchlist_number: item.number,
                            watchlist_title: item.title || '',
                            task_id: this.manualAddSelectedTaskId,
                        }),
                    });
                } else if (this.manualAddLinkTaskMode === 'new' && this.manualAddNewTaskTitle.trim()) {
                    await this.api('/api/personal-todo/link-to-watchlist', {
                        method: 'POST',
                        body: JSON.stringify({
                            watchlist_item_type: item.item_type,
                            watchlist_number: item.number,
                            watchlist_title: item.title || '',
                            new_task_title: this.manualAddNewTaskTitle.trim(),
                            new_task_source: this.manualAddNewTaskSource || 'self',
                        }),
                    });
                }
                // 刷新 watchlist 获取 linked_tasks
                await this.loadWatchlist();

                this.showToast('已加入关注', `#${num} 已加入特别关注`, 'success');
                this.manualAddNumber = '';
                this.manualAddNote = '';
                this.manualAddAssigneeId = null;
                this.manualAddLinkTaskMode = 'none';
                this.manualAddTaskSearchQuery = '';
                this.manualAddTaskSearchResults = [];
                this.manualAddSelectedTaskId = null;
                this.manualAddNewTaskTitle = '';
                this.manualAddNewTaskPriority = 'P2';
                this.manualAddNewTaskSource = 'self';
                this.manualAddSelectedTaskTitle = '';
                // 切换到对应 tab 显示刚添加的项
                this.watchlistTab = item.item_type;
            } catch (e) {
                this.showToast('添加失败', e.message, 'error');
            } finally {
                this.manualAddLoading = false;
                this.showAddWatchlistModal = false;
            }
        },
        openAddWatchlistModal() {
            this.showAddWatchlistModal = true;
            this.focusModalInput();
            this.loadManualAddTaskList();
        },
        // 手动添加 watchlist 时加载任务列表供下拉选择
        async loadManualAddTaskList() {
            this.manualAddTaskSearchLoading = true;
            try {
                const data = await this.api('/api/personal-todo/tasks?per_page=50&status=all');
                this.manualAddTaskSearchResults = data.tasks || [];
            } catch (e) {
                this.showToast('加载任务列表失败', e.message, 'error');
            } finally {
                this.manualAddTaskSearchLoading = false;
            }
        },
        selectManualAddTask(task) {
            this.manualAddSelectedTaskId = task.id;
            this.manualAddSelectedTaskTitle = task.title;
            this.manualAddTaskSearchQuery = '';
            this.manualAddTaskSearchResults = [];
        },

        // ===== Watchlist item editing (note + assignee) =====
        openWatchlistEditModal(w) {
            this.editingWatchlistItem = w;
            this.watchlistEditNote = w.note || '';
            this.watchlistEditAssigneeId = w.assignee_id || null;
            this.watchlistEditLinkTaskId = '';
            this.watchlistEditSelectedTasks = [];
            this.watchlistEditShowCreate = false;
            this.watchlistEditNewTaskTitle = '';
            this.watchlistEditNewTaskSource = 'self';
            this.watchlistEditNewTaskPriority = 'P2';
            this.showWatchlistEditModal = true;
            this._loadWatchlistEditTaskList();
        },

        closeWatchlistEditModal() {
            this.showWatchlistEditModal = false;
            this.editingWatchlistItem = null;
            this.watchlistEditNote = '';
            this.watchlistEditAssigneeId = null;
            this.watchlistEditTaskList = [];
            this.watchlistEditLinkTaskId = '';
            this.watchlistEditSelectedTasks = [];
            this.watchlistEditShowCreate = false;
            this.watchlistEditNewTaskTitle = '';
        },

        watchlistEditAddTask() {
            const id = this.watchlistEditLinkTaskId;
            if (!id) return;
            if (id === '__new__') {
                this.watchlistEditShowCreate = true;
                this.watchlistEditLinkTaskId = '';
                return;
            }
            // 去重
            if (this.watchlistEditSelectedTasks.some(t => t.id === parseInt(id, 10))) return;
            const task = this.watchlistEditTaskList.find(t => t.id === parseInt(id, 10));
            if (task) {
                this.watchlistEditSelectedTasks.push(task);
            }
            this.watchlistEditLinkTaskId = '';
        },
        watchlistEditRemoveTask(taskId) {
            this.watchlistEditSelectedTasks = this.watchlistEditSelectedTasks.filter(t => t.id !== taskId);
        },

        async _loadWatchlistEditTaskList() {
            try {
                const data = await this.api('/api/personal-todo/tasks?per_page=50&status=all');
                this.watchlistEditTaskList = data.tasks || [];
            } catch (_) {
                // 静默失败
            }
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
                // 如果有关联任务操作，执行关联
                for (const t of this.watchlistEditSelectedTasks) {
                    await this.api('/api/personal-todo/link-to-watchlist', {
                        method: 'POST',
                        body: JSON.stringify({
                            watchlist_item_type: w.item_type,
                            watchlist_number: w.number,
                            watchlist_title: w.title || '',
                            task_id: t.id,
                        }),
                    });
                }
                await this.loadWatchlist();
                this._syncDrawerLinkedTasks(w.number, w.item_type);
                this.showToast('关注信息已保存', '', 'success');
                this.closeWatchlistEditModal();
            } catch (e) {
                this.showToast('保存失败', e.message, 'error');
            } finally {
                this.watchlistEditSaving = false;
            }
        },

        async saveWatchlistItemAndCreateTask() {
            if (!this.editingWatchlistItem || !this.watchlistEditNewTaskTitle.trim()) return;
            if (this.watchlistEditSaving) return;
            const w = this.editingWatchlistItem;
            const note = this.watchlistEditNote.trim();
            const assignee_id = this.watchlistEditAssigneeId;
            this.watchlistEditSaving = true;
            try {
                // 先保存备注/责任人
                await this.api(`/api/watchlist/${w.item_type}/${w.number}/note`, {
                    method: 'PUT',
                    body: JSON.stringify({ note, assignee_id }),
                });
                // 创建任务并关联
                await this.api('/api/personal-todo/link-to-watchlist', {
                    method: 'POST',
                    body: JSON.stringify({
                        watchlist_item_type: w.item_type,
                        watchlist_number: w.number,
                        watchlist_title: w.title || '',
                        new_task_title: this.watchlistEditNewTaskTitle.trim(),
                        new_task_source: this.watchlistEditNewTaskSource,
                    }),
                });
                await this.loadWatchlist();
                this._syncDrawerLinkedTasks(w.number, w.item_type);
                this.showToast('已保存并创建任务', '', 'success');
                this.closeWatchlistEditModal();
            } catch (e) {
                this.showToast('操作失败', e.message, 'error');
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
            // 聚焦用户名字段
            this.$nextTick(() => {
                const el = document.querySelector('#user-manager-name');
                if (el) setTimeout(() => el.focus(), 100);
            });
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
            // 如果文章编辑器打开且有未保存修改，阻止切换
            if (this.articleEditorOpen && typeof this.articleFormDirty !== 'undefined' && this.articleFormDirty) {
                if (!confirm('文章有未保存的修改，确定要放弃吗？')) return;
            }
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
            // 保护 contenteditable 元素（如文章编辑器），防止误触发全局快捷键
            if (e.target.closest && e.target.closest('[contenteditable="true"]')) return;
            if (e.target.isContentEditable) return;
            if (e.metaKey || e.ctrlKey || e.altKey) return;

            if (e.key === '1') { e.preventDefault(); this.switchView('community'); }
            else if (e.key === '2') { e.preventDefault(); this.switchView('watchlist'); }
            else if (e.key === '3') { e.preventDefault(); this.switchView('pr-center'); }
            else if (e.key === '4') { e.preventDefault(); this.switchView('personal-todo'); }
            else if (e.key === '5') { e.preventDefault(); this.switchView('intelligence'); }
            else if (e.key === '6') { e.preventDefault(); this.switchView('articles'); }
            else if (e.key === '7') { e.preventDefault(); this.switchView('anatomy'); }
            else if (e.key === 'r' || e.key === 'R') { e.preventDefault(); this.refreshAll(); }
            // 全局 Esc：关闭当前打开的弹窗或抽屉（从最内层到最外层）
            else if (e.key === 'Escape') {
                this.handleGlobalEsc();
            }
        },

        // ===== 全局 Esc 关闭逻辑（从最内层到最外层）=====
        handleGlobalEsc() {
            // 1. 文章编辑器的预览模式
            if (typeof this.closePreview === 'function' && this.articleEditorOpen && this.articleEditorSubView === 'preview') {
                this.closePreview(); return;
            }
            // 2. 插入代码引用弹窗
            if (this.showInsertRef && typeof this.closeInsertRef === 'function') {
                this.closeInsertRef(); return;
            }
            // 3. 文章详情
            if (this.selectedArticle && typeof this.closeArticleView === 'function') {
                this.closeArticleView(); return;
            }
            // 4. 文章编辑器
            if (this.articleEditorOpen && typeof this._confirmDiscard === 'function' && this._confirmDiscard()) {
                this.articleEditorOpen = false; this.articleFormSnapshot = null; return;
            }
            // 5. PR 抽屉
            if (this.selectedPR && typeof this.closePR === 'function') {
                this.closePR(); return;
            }
            // 6. Issue 抽屉
            if (this.selectedIssue && typeof this.closeIssue === 'function') {
                this.closeIssue(); return;
            }
            // 7. 任务详情抽屉
            if (this.selectedTask && typeof this.closeTask === 'function') {
                this.closeTask(); return;
            }
            // 8. 报告查看弹窗
            if (this.selectedReport && typeof this.closeReport === 'function') {
                this.closeReport(); return;
            }
            // 9. 各个模态弹窗（从最内层到最外层）
            if (this.showAddTaskModal) { this.showAddTaskModal = false; return; }
            if (this.showIntelModal) { this.showIntelModal = false; return; }
            if (this.showAddWatchlistModal) { this.showAddWatchlistModal = false; return; }
            if (this.showWatchlistEditModal && typeof this.closeWatchlistEditModal === 'function') {
                this.closeWatchlistEditModal(); return;
            }
            if (this.showUserManager && typeof this.closeUserManager === 'function') {
                this.closeUserManager(); return;
            }
            if (this.showOperatorEditor && typeof this.closeOperatorEditor === 'function') {
                this.closeOperatorEditor(); return;
            }
            if (this.showModelEditor && typeof this.closeModelEditor === 'function') {
                this.closeModelEditor(); return;
            }
            if (this.showCategoryManager) { this.showCategoryManager = false; return; }
            if (this.showOperatorDetail && typeof this.closeOperatorDetail === 'function') {
                this.closeOperatorDetail(); return;
            }
            if (this.showModelDetail && typeof this.closeModelDetail === 'function') {
                this.closeModelDetail(); return;
            }
            // 10. 移动端侧边栏
            if (this.mobileMenuOpen) { this.mobileMenuOpen = false; }
        },

        // ===== Search input handler =====
        onSearchInput(e) {
            this.communityPage = 1;
            // 将全局搜索词同步到各个视图的内部搜索
            const q = (this.searchQuery || '').toLowerCase().trim();
            if (this.currentView === 'anatomy') {
                if (typeof this.operatorSearch !== 'undefined') this.operatorSearch = q;
                if (typeof this.modelSearch !== 'undefined') this.modelSearch = q;
                // 触发各自视图的搜索
                if (typeof this.loadOperators === 'function') this.loadOperators();
                if (typeof this.loadModels === 'function') this.loadModels();
            } else if (this.currentView === 'articles' && typeof this.loadArticles === 'function') {
                // articles 视图已有 articleFilterArea，搜索词可以用于后续筛选
            }
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
                // 不重置 communityLoadingMore，避免与"加载更多"状态冲突
                // 如果用户正在加载更多，静默刷新不应打断
            } catch (_) {}
        },

        // ===== HTML escape helper =====
        esc(s) {
            if (s == null) return '';
            return String(s).replace(/[&<>"']/g, c => ({
                '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
            }[c]));
        },

        // ===== Searchable select state factory =====
        // 创建一个可搜索的选择器状态对象，用于替代大列表 <select>
        createSearchableSelect(initialValue = null) {
            return {
                _value: initialValue,
                _search: '',
                _open: false,
                get value() { return this._value; },
                set value(v) { this._value = v; },
                get search() { return this._search; },
                set search(s) { this._search = s; },
                get open() { return this._open; },
                set open(o) { this._open = o; },
                // 过滤用户列表，排除当前已选
                filtered(users) {
                    if (!this._search.trim()) return users;
                    const q = this._search.toLowerCase().trim();
                    return users.filter(u =>
                        (u.name || '').toLowerCase().includes(q) ||
                        (u.github_id || '').toLowerCase().includes(q)
                    );
                },
                select(user) {
                    this._value = user ? user.id : null;
                    this._search = user ? user.name : '';
                    this._open = false;
                },
                clear() {
                    this._value = null;
                    this._search = '';
                    this._open = false;
                },
                // 初始化：如果已有值，回填显示名称
                initFromValue(users) {
                    if (this._value) {
                        const u = users.find(usr => usr.id === this._value);
                        if (u) this._search = u.name;
                    }
                },
            };
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

// ===== AbortSignal 合并工具 =====
// 将多个 AbortSignal 合并为一个，任一 signal 触发 abort 则合并 signal 也触发
function anySignal(signals) {
    const controller = new AbortController();
    for (const signal of signals) {
        if (signal.aborted) {
            controller.abort(signal.reason);
            return controller.signal;
        }
        signal.addEventListener('abort', () => controller.abort(signal.reason), { once: true });
    }
    return controller.signal;
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
