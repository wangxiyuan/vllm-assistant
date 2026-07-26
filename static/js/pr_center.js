// pr_center.js - PR Command Center 视图

function prCenterMixin() {
    return {
        // ===== PR detail drawer state =====
        selectedPR: null,
        prDetails: null,
        prLoadError: null,
        aiReview: null,
        aiReviewLoading: false,  // AI Review 加载中
        aiReviewElapsed: 0,  // AI Review 已耗时（秒）
        aiReviewTimer: null,
        aiSummary: null,  // PR/Issue AI 总结
        aiSummaryLoading: false,  // AI 总结加载中
        aiSummaryCollapsed: false,  // AI 总结折叠状态
        aiReviewCollapsed: false,  // AI Review 折叠状态
        loadingDetails: false,
        // 进行中的 AI 请求（跨 drawer 开关持久化，关闭再打开能恢复 loading 状态）
        pendingReviews: {},    // { pr_number: true }
        pendingSummaries: {},  // { "type:number": true }

        // ===== Issue detail drawer state =====
        selectedIssue: null,
        issueDetails: null,
        issueLoadError: null,
        loadingIssue: false,

        // ===== 翻译状态 =====
        translateLoading: false,
        prTranslatedBody: null,   // PR 翻译后的中文
        issueTranslatedBody: null, // Issue 翻译后的中文
        prShowChinese: false,     // PR 描述是否显示中文
        issueShowChinese: false,  // Issue 描述是否显示中文

        // ===== Diff 状态 =====
        expandedDiffFile: null,   // 当前展开的 diff 文件名
        fileDiffs: {},            // { filename: diff_text }
        prDiffData: null,         // 原始 diff 全文
        prDiffLoading: false,

        // ===== 贡献面板 tab =====
        contributionTab: 'prs',  // 'prs' or 'issues'
        myIssues: [],
        myIssuesState: 'open',
        myIssuesType: 'all',  // 'all' / 'bug' / 'rfc' / 'feature' / ...
        myIssuesLoading: false,

        // 责任人过滤
        selectedContributor: null,  // {id, name, github_id} 或 null
        selectedContributorGithubId: '',  // 下拉框绑定的字符串
        contributorFilterLoading: false,

        // ===== Switch PR state tab (open/merged/closed/all) =====
        switchPRState(state) {
            this.prState = state;
            // 不重新请求，前端从 allPrs（state=all 缓存）过滤
        },

        switchContributionTab(tab) {
            this.contributionTab = tab;
            if (tab === 'issues') {
                this.loadMyIssues();
            }
        },

        async loadMyIssues() {
            this.myIssuesLoading = true;
            try {
                const githubId = this.selectedContributor?.github_id;
                const url = githubId
                    ? `/api/pr-center/my-issues?state=all&github_id=${encodeURIComponent(githubId)}`
                    : '/api/pr-center/my-issues?state=all';
                this.myIssues = await this.api(url);
            } catch (e) {
                this.showToast('加载 Issue 失败', e.message, 'error');
            } finally {
                this.myIssuesLoading = false;
            }
        },

        switchMyIssuesState(state) {
            this.myIssuesState = state;
        },

        // 前端过滤当前 state 的 PR（allPrs 是完整缓存）
        get filteredMyPRs() {
            const q = (this.searchQuery || '').toLowerCase().trim();
            let list = this.myPrs;
            if (this.prState !== 'all') {
                list = list.filter(p => p.state === this.prState);
            }
            if (this.filterConflicts) {
                list = list.filter(p => p.conflict_detected);
            }
            if (this.filterCIFail) {
                list = list.filter(p => p.ci_status === 'fail');
            }
            if (q) {
                list = list.filter(p =>
                    (p.title || '').toLowerCase().includes(q) ||
                    String(p.pr_number).includes(q) ||
                    (p.branch || '').toLowerCase().includes(q)
                );
            }
            return list;
        },

        get filteredMyIssues() {
            const q = (this.searchQuery || '').toLowerCase().trim();
            let list = this.myIssues;
            if (this.myIssuesState !== 'all') {
                list = list.filter(i => i.state === this.myIssuesState);
            }
            if (this.myIssuesType !== 'all') {
                list = list.filter(i => this.issueType(i) === this.myIssuesType);
            }
            if (q) {
                list = list.filter(i =>
                    (i.title || '').toLowerCase().includes(q) ||
                    String(i.number).includes(q)
                );
            }
            return list;
        },

        // 各 issue 类型的计数（用于 tab badge）
        get myIssueTypeCounts() {
            const counts = { all: this.myIssues.length };
            for (const i of this.myIssues) {
                const t = this.issueType(i);
                counts[t] = (counts[t] || 0) + 1;
            }
            return counts;
        },

        switchMyIssuesType(type) {
            this.myIssuesType = type;
        },

        // 各状态 PR 计数（基于完整缓存）
        get openPRCount() {
            return this.myPrs.filter(p => p.state === 'open').length;
        },
        get mergedPRCount() {
            return this.myPrs.filter(p => p.state === 'merged').length;
        },
        get closedPRCount() {
            return this.myPrs.filter(p => p.state === 'closed').length;
        },
        get allPRCount() {
            return this.myPrs.length;
        },

        get openIssueCount() {
            return this.myIssues.filter(i => i.state === 'open').length;
        },
        get closedIssueCount() {
            return this.myIssues.filter(i => i.state === 'closed').length;
        },
        get allIssueCount() {
            return this.myIssues.length;
        },

        async loadMyPRs() {
            try {
                const githubId = this.selectedContributor?.github_id;
                const url = githubId
                    ? `/api/pr-center/my-prs?state=all&github_id=${encodeURIComponent(githubId)}`
                    : '/api/pr-center/my-prs?state=all';
                this.myPrs = await this.api(url);
            } catch (e) {
                this.showToast('加载 PR 失败', e.message, 'error');
            }
        },

        // 切换责任人过滤
        switchContributor(githubId) {
            if (githubId) {
                this.selectedContributor = this.users.find(u => u.github_id === githubId) || null;
                this.selectedContributorGithubId = githubId || '';
            } else {
                this.selectedContributor = null;
                this.selectedContributorGithubId = '';
            }
            this.loadAllContribData();
        },

        // 加载选中的责任人所有贡献数据
        loadAllContribData() {
            this.loadMyStats();
            this.loadMyPRs();
            if (this.contributionTab === 'issues') {
                this.loadMyIssues();
            }
        },

        async openPR(pr) {
            // 合并 watchlist 数据（备注/责任人/关联任务）
            const wl = this.findWatchlistItem(pr.pr_number, 'pr');
            if (wl) {
                pr.watchlist_note = wl.note || '';
                pr.watchlist_assignee_id = wl.assignee_id || null;
                pr._linked_tasks = wl.linked_tasks || [];
            } else if (pr._linked_tasks) {
                // 从 openWatchlistPR 直接传入的 linked_tasks
                pr._linked_tasks = pr._linked_tasks || [];
            }
            this.selectedPR = pr;
            this.prDetails = null;
            this.prLoadError = null;
            this.aiReview = null;
            this.aiSummary = null;
            this.aiSummaryCollapsed = false;
            this.aiReviewCollapsed = false;
            this.loadingDetails = true;
            // 恢复进行中的 review 状态（关闭再打开时显示 loading）
            this.aiReviewLoading = !!this.pendingReviews[pr.pr_number];
            this.aiSummaryLoading = !!this.pendingSummaries['pr:' + pr.pr_number];
            try {
                this.prDetails = await this.api(`/api/pr-center/my-prs/${pr.pr_number}/details`);
                // 异步读取 AI 缓存（不阻塞详情加载）
                this._loadCachedAI('pr', pr.pr_number);
                // 异步读取翻译缓存
                this._loadCachedTranslate('pr', pr.pr_number);
            } catch (e) {
                this.prLoadError = e.message;
                this.showToast('加载 PR 详情失败', e.message, 'error');
            } finally {
                this.loadingDetails = false;
            }
            this._scrollDrawerToTop();
        },

        closePR() {
            this.selectedPR = null;
            this.prDetails = null;
            this.prLoadError = null;
            this.aiReview = null;
            this.aiSummary = null;
            this.loadingDetails = false;
            if (this.aiReviewTimer) { clearInterval(this.aiReviewTimer); this.aiReviewTimer = null; }
            this.aiReviewElapsed = 0;
            this.prTranslatedBody = null;
            this.prShowChinese = false;
            this.expandedDiffFile = null;
            this.fileDiffs = {};
            this.prDiffData = null;
            // 不重置 pendingReviews/pendingSummaries，让进行中的请求继续
            // 不重置 aiReviewLoading/aiSummaryLoading（下次 openPR 会根据 pending 状态恢复）
        },

        // ===== Issue drawer =====
        async openIssue(issue) {
            // 合并 watchlist 数据（备注/责任人/关联任务）
            const wl = this.findWatchlistItem(issue.number, 'issue');
            if (wl) {
                issue.watchlist_note = wl.note || '';
                issue.watchlist_assignee_id = wl.assignee_id || null;
                issue._linked_tasks = wl.linked_tasks || [];
            } else {
                issue._linked_tasks = issue._linked_tasks || [];
            }
            this.selectedIssue = issue;
            this.issueDetails = issue.body ? issue : null;
            this.issueLoadError = null;
            this.aiSummary = null;
            this.aiSummaryCollapsed = false;
            this.aiSummaryLoading = !!this.pendingSummaries['issue:' + issue.number];
            this.loadingIssue = !issue.body;
            try {
                if (!issue.body) {
                    this.issueDetails = await this.api(`/api/pr-center/issue/${issue.number}/body`);
                }
                // 异步读取 AI 缓存
                this._loadCachedAI('issue', issue.number);
                // 异步读取翻译缓存
                this._loadCachedTranslate('issue', issue.number);
            } catch (e) {
                this.issueLoadError = e.message;
                this.showToast('加载 Issue 失败', e.message, 'error');
            } finally {
                this.loadingIssue = false;
            }
            this._scrollDrawerToTop();
        },

        closeIssue() {
            this.selectedIssue = null;
            this.issueDetails = null;
            this.issueLoadError = null;
            this.aiSummary = null;
            this.loadingIssue = false;
            this.issueTranslatedBody = null;
            this.issueShowChinese = false;
        },

        // 读取本地缓存的 AI 结果（summary/review），打开 drawer 时自动填充
        async _loadCachedAI(itemType, number) {
            try {
                // summary 缓存
                const cachedSummary = await this.api('/api/ai-assistant/get-cache', {
                    method: 'POST',
                    body: JSON.stringify({ item_type: itemType, number, action: 'summary' }),
                }, 5000);
                // 只在当前 drawer 匹配时更新 UI
                const isCurrent = (itemType === 'pr' && this.selectedPR?.pr_number === number)
                               || (itemType === 'issue' && this.selectedIssue?.number === number);
                if (!isCurrent) return;
                if (cachedSummary && !cachedSummary.empty) {
                    this.aiSummary = this.renderSummary(cachedSummary);
                }
                // review 缓存（仅 PR）
                if (itemType === 'pr') {
                    const cachedReview = await this.api('/api/ai-assistant/get-cache', {
                        method: 'POST',
                        body: JSON.stringify({ item_type: itemType, number, action: 'review' }),
                    }, 5000);
                    const stillCurrent = this.selectedPR?.pr_number === number;
                    if (!stillCurrent) return;
                    if (cachedReview && !cachedReview.empty) {
                        this.aiReview = cachedReview;
                    }
                }
            } catch (e) {
                // 缓存读取失败静默忽略
            }
        },

        // 读取翻译缓存，打开 drawer 时自动填充
        async _loadCachedTranslate(itemType, number) {
            try {
                const cached = await this.api('/api/ai-assistant/get-cache', {
                    method: 'POST',
                    body: JSON.stringify({ item_type: itemType, number, action: 'translate' }),
                }, 5000);
                const isCurrent = (itemType === 'pr' && this.selectedPR?.pr_number === number)
                               || (itemType === 'issue' && this.selectedIssue?.number === number);
                if (!isCurrent) return;
                if (cached && cached.translated) {
                    if (itemType === 'pr') {
                        this.prTranslatedBody = cached.translated;
                    } else {
                        this.issueTranslatedBody = cached.translated;
                    }
                }
            } catch (e) {
                // 缓存读取失败静默忽略
            }
        },

        // ===== 加载 PR diff 全文 =====
        async loadPRDiff() {
            if (!this.selectedPR?.pr_number) return;
            if (this.prDiffLoading) return;
            this.prDiffLoading = true;
            try {
                const data = await this.api(`/api/pr-center/my-prs/${this.selectedPR.pr_number}/diff`, {}, 60000);
                this.prDiffData = data.diff || '';
                // 按文件拆分 diff
                this._parseDiffFiles(this.prDiffData);
            } catch (e) {
                this.showToast('加载 diff 失败', e.message, 'error');
            } finally {
                this.prDiffLoading = false;
            }
        },

        // 解析 diff 全文，按文件拆分
        _parseDiffFiles(rawDiff) {
            if (!rawDiff) return;
            const files = {};
            const fileBlocks = rawDiff.split(/(?=^diff --git )/m);
            for (const block of fileBlocks) {
                if (!block.trim()) continue;
                const m = block.match(/^diff --git a\/(\S+) b\/(\S+)/m);
                if (m) {
                    const filename = m[2];
                    files[filename] = block;
                }
            }
            this.fileDiffs = files;
        },

        // 切换文件 diff 展开/收起
        toggleFileDiff(filename) {
            if (this.expandedDiffFile === filename) {
                this.expandedDiffFile = null;
                return;
            }
            this.expandedDiffFile = filename;
            // 如果还没加载 diff 且该文件 diff 不存在，加载全部
            if (!this.fileDiffs[filename] && !this.prDiffLoading) {
                this.loadPRDiff();
            }
        },

        // 渲染带行号和高亮的 diff HTML
        renderDiff(diffText) {
            if (!diffText) return '';
            const lines = diffText.split('\n');
            const out = [];
            let lineNum = 0;
            for (const line of lines) {
                if (line.startsWith('@@')) {
                    // hunk header: 提取新文件起始行号
                    const m = line.match(/@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
                    if (m) lineNum = parseInt(m[1], 10);
                    out.push(`<div class="diff-hunk-header">${this.esc(line)}</div>`);
                    continue;
                }
                if (line.startsWith('diff --git') || line.startsWith('index ') || line.startsWith('---') || line.startsWith('+++')) {
                    out.push(`<div class="diff-meta">${this.esc(line)}</div>`);
                    continue;
                }
                if (line.startsWith('+')) {
                    out.push(`<div class="diff-line diff-add"><span class="diff-line-num">${lineNum}</span><span>${this.esc(line)}</span></div>`);
                    lineNum++;
                } else if (line.startsWith('-')) {
                    out.push(`<div class="diff-line diff-del"><span class="diff-line-num">${lineNum}</span><span>${this.esc(line)}</span></div>`);
                } else if (line.startsWith('\\')) {
                    out.push(`<div class="diff-line diff-no-newline"><span>${this.esc(line)}</span></div>`);
                } else {
                    out.push(`<div class="diff-line diff-ctx"><span class="diff-line-num">${lineNum}</span><span>${this.esc(line)}</span></div>`);
                    lineNum++;
                }
            }
            return out.join('\n');
        },

        // ===== AI 翻译 =====
        async translateBody(itemType) {
            if (this.translateLoading) return;
            const isPR = itemType === 'pr';
            const number = isPR ? (this.selectedPR?.pr_number) : (this.selectedIssue?.number);
            const body = isPR ? (this.prDetails?.pr?.body || '') : (this.issueDetails?.body || '');
            if (!body) {
                this.showToast('无内容可翻译', '', 'info');
                return;
            }
            this.translateLoading = true;
            try {
                const result = await this.api('/api/ai-assistant/translate', {
                    method: 'POST',
                    body: JSON.stringify({
                        item_type: itemType,
                        number: number,
                        text: body,
                    }),
                }, 120000);
                if (isPR) {
                    this.prTranslatedBody = result.translated;
                    this.prShowChinese = true;
                } else {
                    this.issueTranslatedBody = result.translated;
                    this.issueShowChinese = true;
                }
                this.showToast('翻译完成', '', 'success');
            } catch (e) {
                this.showToast('翻译失败', e.message, 'error');
            } finally {
                this.translateLoading = false;
            }
        },

        // ===== AI 总结（PR/Issue 通用）=====
        async generateSummary(itemType) {
            const isPR = itemType === 'pr';
            const data = isPR ? this.selectedPR : this.selectedIssue;
            if (!data) return;
            if (this.aiSummaryLoading) return;  // 防止重复点击
            const number = data.number || data.pr_number;
            const pendingKey = itemType + ':' + number;
            this.aiSummary = null;
            this.aiSummaryLoading = true;
            this.aiSummaryCollapsed = false;
            this.pendingSummaries[pendingKey] = true;
            // 先清除旧缓存，确保重新生成
            try {
                await this.api('/api/ai-assistant/clear-cache', {
                    method: 'POST',
                    body: JSON.stringify({ item_type: itemType, number: number, action: 'summary' }),
                }, 5000);
            } catch (_) {}
            try {
                const body = isPR ? (this.prDetails?.pr?.body || '') : (this.issueDetails?.body || '');
                const res = await this.api('/api/ai-assistant/summarize', {
                    method: 'POST',
                    body: JSON.stringify({
                        item_type: itemType,
                        number: number,
                        title: data.title || '',
                        body: body,
                    }),
                }, 120000);  // 给 120s 超时
                // 只在当前 drawer 匹配时更新 UI
                const isCurrent = (isPR && this.selectedPR?.pr_number === number)
                               || (!isPR && this.selectedIssue?.number === number);
                if (isCurrent) {
                    // res is now the summary dict directly (core_problem, key_points, etc.)
                    this.aiSummary = this.renderSummary(res);
                }
            } catch (e) {
                const isCurrent = (isPR && this.selectedPR?.pr_number === number)
                               || (!isPR && this.selectedIssue?.number === number);
                if (isCurrent) {
                    this.aiSummary = `<p style="color: var(--signal-red);">总结失败：${this.esc(e.message)}</p>`;
                }
            } finally {
                delete this.pendingSummaries[pendingKey];
                if (this.selectedPR?.pr_number === number || this.selectedIssue?.number === number) {
                    this.aiSummaryLoading = false;
                }
            }
        },

        // ===== 轻量 Markdown 渲染（仅前端，无外部依赖）=====
        renderMarkdown(text) {
            if (!text) return '';
            // 统一换行符：GitHub API 返回 CRLF (\r\n)，去掉 \r 避免正则 $ 锚点失效
            let normalized = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
            const lines = normalized.split('\n');
            const out = [];
            let inList = null;  // 'ul' | 'ol' | null
            let inCode = false;
            let codeLines = [];
            let inTable = false;
            let tableLines = [];
            let blockquoteLines = [];
            let inDetails = false;  // 是否在 <details> 块内
            let detailsSummary = '';
            let detailsBody = [];

            const flushList = () => {
                if (inList) { out.push(`</${inList}>`); inList = null; }
            };
            const flushBlockquote = () => {
                if (blockquoteLines.length) {
                    out.push(`<blockquote>${this.renderInlineMarkdown(blockquoteLines.join(' '))}</blockquote>`);
                    blockquoteLines = [];
                }
            };
            const flushTable = () => {
                if (tableLines.length >= 2) {
                    const headers = this.parseTableRow(tableLines[0]);
                    const rows = tableLines.slice(2).map(l => this.parseTableRow(l));
                    let h = '<table><thead><tr>';
                    headers.forEach(c => h += `<th>${this.renderInlineMarkdown(c)}</th>`);
                    h += '</tr></thead><tbody>';
                    rows.forEach(r => {
                        h += '<tr>';
                        r.forEach(c => h += `<td>${this.renderInlineMarkdown(c)}</td>`);
                        h += '</tr>';
                    });
                    h += '</tbody></table>';
                    out.push(h);
                }
                tableLines = [];
                inTable = false;
            };
            const flushDetails = () => {
                if (inDetails) {
                    // details 内的内容递归渲染 Markdown
                    const renderedBody = this.renderMarkdown(detailsBody.join('\n'));
                    out.push(`<details><summary>${this.renderInlineMarkdown(this.esc(detailsSummary))}</summary>${renderedBody}</details>`);
                    inDetails = false;
                    detailsSummary = '';
                    detailsBody = [];
                }
            };

            for (let i = 0; i < lines.length; i++) {
                const line = lines[i];

                // 独立 <img> 标签（GitHub issue/PR 常用截图）
                const imgMatch = line.match(/^\s*<img\s+[^>]*src\s*=\s*"([^"]+)"[^>]*\/?>\s*$/i);
                if (imgMatch) {
                    flushList(); flushBlockquote(); flushTable();
                    // 安全过滤：移除 on* 事件处理器
                    const safeLine = line.replace(/\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '');
                    const alt = safeLine.match(/alt\s*=\s*"([^"]+)"/i);
                    const altText = alt ? alt[1] : '';
                    out.push(`<img src="${this.esc(imgMatch[1])}" alt="${this.esc(altText)}" style="max-width:100%;border-radius:var(--radius);margin:var(--space-3) 0;" />`);
                    continue;
                }

                // <details> 折叠块
                const detailsMatch = line.match(/^\s*<details>/i);
                const detailsCloseMatch = line.match(/^\s*<\/details>/i);
                if (detailsMatch) {
                    flushList(); flushBlockquote(); flushTable();
                    inDetails = true;
                    detailsSummary = '';
                    detailsBody = [];
                    // 检查同一行是否有 <summary>
                    const summaryMatch = line.match(/<summary>([^<]*)<\/summary>/i);
                    if (summaryMatch) {
                        detailsSummary = summaryMatch[1];
                    }
                    continue;
                }
                if (inDetails) {
                    if (detailsCloseMatch) {
                        flushDetails();
                        continue;
                    }
                    const summaryMatch = line.match(/^\s*<summary>([^<]*)<\/summary>\s*$/i);
                    if (summaryMatch) {
                        detailsSummary = summaryMatch[1];
                        continue;
                    }
                    // details 内的内容先跳过 Markdown 渲染（简单存文本）
                    detailsBody.push(line);
                    continue;
                }

                // 代码块
                if (line.trim().startsWith('```')) {
                    flushList(); flushBlockquote(); flushTable();
                    if (!inCode) {
                        inCode = true;
                        codeLines = [];
                    } else {
                        out.push(`<pre><code>${this.esc(codeLines.join('\n'))}</code></pre>`);
                        inCode = false;
                    }
                    continue;
                }
                if (inCode) { codeLines.push(line); continue; }

                // 表格
                if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
                    flushList(); flushBlockquote();
                    if (!inTable) inTable = true;
                    tableLines.push(line.trim());
                    continue;
                } else if (inTable) {
                    flushTable();
                }

                // 标题
                const hMatch = line.match(/^(#{1,6})\s+(.*)$/);
                if (hMatch) {
                    flushList(); flushBlockquote();
                    const level = hMatch[1].length;
                    out.push(`<h${level}>${this.renderInlineMarkdown(hMatch[2])}</h${level}>`);
                    continue;
                }

                // 引用
                if (line.startsWith('>')) {
                    flushList();
                    blockquoteLines.push(line.replace(/^>\s?/, ''));
                    continue;
                } else if (blockquoteLines.length) {
                    flushBlockquote();
                }

                // 水平线
                if (/^[-*_]{3,}$/.test(line.trim())) {
                    flushList();
                    out.push('<hr>');
                    continue;
                }

                // 列表
                const ulMatch = line.match(/^[\s]*[-*+]\s+(.*)$/);
                const olMatch = line.match(/^[\s]*\d+\.\s+(.*)$/);
                if (ulMatch || olMatch) {
                    const tag = olMatch ? 'ol' : 'ul';
                    const raw = (olMatch || ulMatch)[1];
                    // 处理 task list: - [ ] / - [x]
                    const taskMatch = raw.match(/^\[([ xX])\]\s+(.*)$/);
                    if (taskMatch) {
                        const checked = taskMatch[1].toLowerCase() === 'x';
                        const text = this.renderInlineMarkdown(taskMatch[2]);
                        if (inList && inList !== tag) flushList();
                        if (!inList) { out.push(`<${tag}>`); inList = tag; }
                        out.push(`<li><input type="checkbox" disabled${checked ? ' checked' : ''}> ${text}</li>`);
                    } else {
                        if (inList && inList !== tag) flushList();
                        if (!inList) { out.push(`<${tag}>`); inList = tag; }
                        out.push(`<li>${this.renderInlineMarkdown(raw)}</li>`);
                    }
                    continue;
                } else {
                    flushList();
                }

                // 空行
                if (!line.trim()) continue;

                // 普通段落
                out.push(`<p>${this.renderInlineMarkdown(line)}</p>`);
            }
            flushList(); flushBlockquote(); flushTable();
            if (inCode) out.push(`<pre><code>${this.esc(codeLines.join('\n'))}</code></pre>`);
            return out.join('\n');
        },

        // 行内 markdown：粗体/斜体/代码/链接
        renderInlineMarkdown(text) {
            if (!text) return '';

            // 先处理 HTML 标签（img 等），避免被 esc 转义
            let s = text;
            // 保存 <img> 标签，跳过 esc
            const preserved = [];
            s = s.replace(/<img\s+[^>]*src\s*=\s*"([^"]+)"[^>]*\/?>/gi, function(match) {
                // 安全过滤：移除 on* 事件处理器
                const safe = match.replace(/\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '');
                const idx = preserved.length;
                preserved.push(safe);
                return `\x00IMG${idx}\x00`;
            });
            // 保存 <a> 标签
            s = s.replace(/<a\s+[^>]*>.*?<\/a>/gi, function(match) {
                // 安全过滤：移除 on* 事件处理器和 javascript: 链接
                let safe = match.replace(/\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '');
                safe = safe.replace(/\bhref\s*=\s*(?:"javascript:[^"]*"|'javascript:[^']*')/gi, 'href="#"');
                const idx = preserved.length;
                preserved.push(safe);
                return `\x00HTML${idx}\x00`;
            });

            s = this.esc(s);

            // 恢复被保护的 HTML 标签
            s = s.replace(/\x00IMG(\d+)\x00/g, function(_, idx) { return preserved[parseInt(idx)]; });
            s = s.replace(/\x00HTML(\d+)\x00/g, function(_, idx) { return preserved[parseInt(idx)]; });

            // 行内代码
            s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
            // 粗体
            s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
            s = s.replace(/__([^_]+)__/g, '<strong>$1</strong>');
            // 斜体
            s = s.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
            // Markdown 图片 ![alt](url)
            s = s.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, function(match, alt, url) {
                if (/^(https?:|data:)/i.test(url)) {
                    return '<img src="' + url + '" alt="' + alt + '" style="max-width:100%;border-radius:var(--radius);" />';
                }
                return match;
            });
            // 链接 [text](url) — 只允许 http/https/mailto 协议，防止 javascript: XSS
            s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function(match, text, url) {
                if (/^(https?:|mailto:)/i.test(url)) {
                    return '<a href="' + url + '" target="_blank" rel="noopener">' + text + '</a>';
                }
                return text;
            });
            // 裸链接 — 只允许 http/https
            s = s.replace(/(^|[^"\'>=])(https?:\/\/[^\s<]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
            // 安全过滤：移除所有 HTML 标签上的 on* 事件处理器和 javascript: URL
            s = s.replace(/\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '');
            s = s.replace(/\bhref\s*=\s*(?:"javascript:[^"]*"|'javascript:[^']*'|javascript:[^\s>]+)/gi, 'href="#"');
            s = s.replace(/\bsrc\s*=\s*(?:"javascript:[^"]*"|'javascript:[^']*'|javascript:[^\s>]+)/gi, 'src="#"');
            return s;
        },

        parseTableRow(line) {
            return line.split('|').slice(1, -1).map(c => c.trim());
        },

        async generateReview() {
            if (!this.selectedPR) return;
            if (this.aiReviewLoading) return;  // 防止重复点击
            const prNumber = this.selectedPR.pr_number;
            this.aiReview = null;
            this.aiReviewLoading = true;
            this.aiReviewElapsed = 0;
            this.aiReviewCollapsed = false;
            this.pendingReviews[prNumber] = true;
            // 启动计时器
            if (this.aiReviewTimer) clearInterval(this.aiReviewTimer);
            this.aiReviewTimer = setInterval(() => {
                this.aiReviewElapsed++;
            }, 1000);
            // 先清除旧缓存，确保重新生成
            try {
                await this.api('/api/ai-assistant/clear-cache', {
                    method: 'POST',
                    body: JSON.stringify({ item_type: 'pr', number: prNumber, action: 'review' }),
                }, 5000);
            } catch (_) {}
            try {
                const review = await this.api('/api/ai-assistant/generate-review', {
                    method: 'POST',
                    body: JSON.stringify({
                        pr_number: prNumber,
                        include_diff: true,
                    }),
                }, 150000);  // AI Review 给 150s 超时（diff 处理较慢）
                // 只在当前 drawer 匹配时更新 UI
                if (this.selectedPR?.pr_number === prNumber) {
                    this.aiReview = review;
                    if (review.error) {
                        this.showToast('AI Review 异常', review.error, 'error');
                    }
                }
            } catch (e) {
                if (this.selectedPR?.pr_number === prNumber) {
                    this.aiReview = { error: e.message };
                    this.showToast('AI Review 失败', e.message, 'error');
                }
            } finally {
                delete this.pendingReviews[prNumber];
                if (this.aiReviewTimer) { clearInterval(this.aiReviewTimer); this.aiReviewTimer = null; }
                if (this.selectedPR?.pr_number === prNumber) {
                    this.aiReviewLoading = false;
                }
            }
        },

        // ===== AI 总结渲染（结构化）=====
        renderSummary(summaryData) {
            if (!summaryData) return '';
            try {
                // summaryData is now a dict directly (core_problem, key_points, etc.)
                let data = summaryData;
                if (typeof summaryData === 'string') {
                    // Fallback: try parsing as JSON string
                    let s = summaryData.trim();
                    if (s.startsWith('```')) {
                        s = s.replace(/^```(?:json)?\n?/, '').replace(/\n?```$/, '');
                    }
                    data = JSON.parse(s);
                }

                let html = '';
                if (data.core_problem) {
                    html += `<p><strong>核心问题：</strong> ${this.esc(String(data.core_problem))}</p>`;
                }
                if (Array.isArray(data.key_points) && data.key_points.length > 0) {
                    html += `<h4>关键要点</h4><ul>`;
                    for (const p of data.key_points) {
                        html += `<li>${this.esc(String(p))}</li>`;
                    }
                    html += `</ul>`;
                }
                if (data.impact) {
                    html += `<p><strong>影响范围：</strong> ${this.esc(String(data.impact))}</p>`;
                }
                if (data.risk && data.risk !== '暂无') {
                    html += `<p><strong>潜在风险：</strong> <span class="severity-important">${this.esc(String(data.risk))}</span></p>`;
                } else if (data.risk === '暂无') {
                    html += `<p><strong>潜在风险：</strong> <span style="color: var(--text-tertiary);">暂无</span></p>`;
                }
                return html || `<p>${this.esc(String(summaryData))}</p>`;
            } catch (e) {
                // 解析失败，当作纯文本渲染
                return `<p>${this.esc(String(summaryData))}</p>`;
            }
        },

        // ===== 状态标签文本（中文）=====

        _scrollDrawerToTop() {
            // 使用 nextTick 确保 DOM 已更新
            setTimeout(() => {
                const drawerBody = document.querySelector('.drawer-body');
                if (drawerBody) drawerBody.scrollTop = 0;
            }, 50);
        },

        ciLabel(status) {
            return {'pass': 'CI 通过', 'fail': 'CI 失败', 'pending': 'CI 进行中', 'unknown': 'CI 未知'}[status] || 'CI';
        },

        severityLabel(sev) {
            return {'critical': '严重', 'important': '重要', 'minor': '次要', 'high': '高', 'medium': '中', 'low': '低'}[(sev || '').toLowerCase()] || sev;
        },

        // ===== Badge class helpers =====
        ciBadgeClass(status) {
            return {
                'pass': 'badge-ci-pass',
                'fail': 'badge-ci-fail',
                'pending': 'badge-ci-pending',
                'unknown': 'badge-ci-unknown',
            }[status] || 'badge-ci-unknown';
        },

        // ===== 结构化 AI 结果渲染 =====
        renderReview(review) {
            if (!review) return '';
            // try-catch 保护：任何渲染异常都不应导致 Alpine 组件崩溃
            try {
                // 错误/原始 fallback（仅当 review 只有 raw_response 没有结构化字段时）
                const hasStructuredData = Array.isArray(review.code_quality) || Array.isArray(review.tests);
                if (!hasStructuredData) {
                    const fallback = this.renderAIJSON(review);
                    if (fallback) return fallback;
                }

                let html = '';

                // 总体评价
                if (review.summary) {
                    html += `<p><strong>总体评价：</strong> ${this.esc(String(review.summary))}</p>`;
                }

                // 分节渲染辅助函数（兼容数组和字符串两种格式）
                const renderSection = (title, items, icon = '') => {
                    try {
                        // 字符串：直接作为段落渲染
                        if (typeof items === 'string' && items.trim()) {
                            return `<h4>${icon} ${this.esc(title)}</h4><p>${this.esc(items)}</p>`;
                        }
                        // 数组：逐项渲染
                        if (!Array.isArray(items) || items.length === 0) return '';
                        let h = `<h4>${icon} ${this.esc(title)}</h4><ul>`;
                        for (const item of items) {
                            if (typeof item === 'string') {
                                h += `<li>${this.esc(item)}</li>`;
                            } else if (item && typeof item === 'object') {
                                const severity = item.severity || item.level || '';
                                const sevClass = severity ? ` class="severity-${String(severity).toLowerCase()}"` : '';
                                const sevTag = severity ? `<span${sevClass}>[${this.esc(this.severityLabel(severity))}]</span> ` : '';
                                const desc = item.description || item.comment || item.message || item.explanation || '';
                                const itemTitle = item.title || item.name || item.concern || '';
                                // 如果有 title 则加粗显示，否则只显示描述
                                if (itemTitle) {
                                    h += `<li>${sevTag}<strong>${this.esc(String(itemTitle))}</strong>`;
                                    if (desc) h += ` - ${this.esc(String(desc))}`;
                                    h += `</li>`;
                                } else {
                                    h += `<li>${sevTag}${this.esc(String(desc || ''))}</li>`;
                                }
                            }
                        }
                        h += `</ul>`;
                        return h;
                    } catch (e) {
                        return '';
                    }
                };

                html += renderSection('代码质量', review.code_quality, '◆');
                html += renderSection('性能', review.performance, '⚡');
                html += renderSection('测试', review.tests, '✓');
                html += renderSection('文档', review.docs, '📄');

                // 如果有 raw_response（JSON 解析失败时的兜底），追加可折叠原始内容
                if (review.raw_response) {
                    html += `<details style="margin-top: 12px;"><summary style="cursor: pointer; font-size: 12px; color: var(--text-tertiary);">查看 AI 原始返回</summary><pre class="ai-raw" style="margin-top: 8px;">${this.esc(String(review.raw_response))}</pre></details>`;
                }

                return html || '<p class="text-tertiary">未返回结构化反馈</p>';
            } catch (e) {
                return `<p style="color: var(--signal-red);">渲染失败：${this.esc(e.message)}</p>`;
            }
        },

        // ===== 贡献概览数据（原 my-data）=====
        myStats: null,
        statsLoading: false,

        async loadMyStats() {
            this.statsLoading = true;
            try {
                const githubId = this.selectedContributor?.github_id;
                const url = githubId
                    ? `/api/my-stats?github_id=${encodeURIComponent(githubId)}`
                    : '/api/my-stats';
                this.myStats = await this.api(url);
            } catch (e) {
                this.showToast('加载数据失败', e.message, 'error');
            } finally {
                this.statsLoading = false;
            }
        },


        // ===== Monthly bar chart helpers =====
        // 月度柱状图高度计算（百分比归一化）
        monthBarHeight(count, allMonthly) {
            const max = Math.max(...Object.values(allMonthly), 1);
            return Math.round((count / max) * 100);
        },

        // 月份标签：每年第一个月显示年份，否则只显示月份
        formatMonthLabel(month) {
            if (!month) return '';
            const [year, mon] = month.split('-');
            const all = Object.keys(this.myStats?.monthly?.created || {});
            const sameYearMonths = all.filter(m => m.startsWith(year + '-'));
            if (sameYearMonths[0] === month) {
                return year.slice(2) + '/' + mon;
            }
            return mon;
        },
    };
}
