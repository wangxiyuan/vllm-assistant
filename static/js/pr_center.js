// pr_center.js - PR Command Center 视图

function prCenterMixin() {
    return {
        // ===== PR detail drawer state =====
        selectedPR: null,
        prDetails: null,
        aiReview: null,
        aiReviewLoading: false,  // AI Review 加载中
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
        loadingIssue: false,

        // ===== 我的贡献 tab =====
        contributionTab: 'prs',  // 'prs' or 'issues'
        myIssues: [],
        myIssuesState: 'open',
        myIssuesType: 'all',  // 'all' / 'bug' / 'rfc' / 'feature' / ...
        myIssuesLoading: false,

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
                const params = new URLSearchParams({ state: 'all' });
                this.myIssues = await this.api('/api/pr-center/my-issues?' + params);
            } catch (e) {
                this.showToast('加载我的 Issue 失败', e.message, 'error');
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
                // 始终加载全部 PR（state=all），前端按 state 过滤显示
                // 这样切 tab 不需要重新请求，且能显示各状态计数
                this.myPrs = await this.api('/api/pr-center/my-prs?state=all');
            } catch (e) {
                this.showToast('加载 PR 失败', e.message, 'error');
            }
        },

        async openPR(pr) {
            this.selectedPR = pr;
            this.prDetails = null;
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
            } catch (e) {
                this.showToast('加载 PR 详情失败', e.message, 'error');
            } finally {
                this.loadingDetails = false;
            }
        },

        closePR() {
            this.selectedPR = null;
            this.prDetails = null;
            this.aiReview = null;
            this.aiSummary = null;
            this.loadingDetails = false;
            // 不重置 pendingReviews/pendingSummaries，让进行中的请求继续
            // 不重置 aiReviewLoading/aiSummaryLoading（下次 openPR 会根据 pending 状态恢复）
        },

        // ===== Issue drawer =====
        async openIssue(issue) {
            this.selectedIssue = issue;
            this.issueDetails = issue.body ? issue : null;
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
            } catch (e) {
                this.showToast('加载 Issue 失败', e.message, 'error');
            } finally {
                this.loadingIssue = false;
            }
        },

        closeIssue() {
            this.selectedIssue = null;
            this.issueDetails = null;
            this.aiSummary = null;
            this.loadingIssue = false;
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
                if (cachedSummary && cachedSummary.summary) {
                    this.aiSummary = this.renderSummary(cachedSummary.summary);
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
                const body = isPR ? (this.prDetails?.body || '') : (this.issueDetails?.body || '');
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
            const lines = text.split('\n');
            const out = [];
            let inList = null;  // 'ul' | 'ol' | null
            let inCode = false;
            let codeLines = [];
            let inTable = false;
            let tableLines = [];
            let blockquoteLines = [];

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

            for (let i = 0; i < lines.length; i++) {
                const line = lines[i];
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
                    const content = (olMatch || ulMatch)[1];
                    if (inList && inList !== tag) flushList();
                    if (!inList) { out.push(`<${tag}>`); inList = tag; }
                    out.push(`<li>${this.renderInlineMarkdown(content)}</li>`);
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
            let s = this.esc(text);
            // 行内代码
            s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
            // 粗体
            s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
            s = s.replace(/__([^_]+)__/g, '<strong>$1</strong>');
            // 斜体
            s = s.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
            // 链接 [text](url)
            s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
            // 裸链接
            s = s.replace(/(?<!["'>])(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
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
            this.aiReviewCollapsed = false;
            this.pendingReviews[prNumber] = true;
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
                // 错误/原始 fallback
                const fallback = this.renderAIJSON(review);
                if (fallback) return fallback;

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
                html += renderSection('建议 Reviewer（基于 CODEOWNERS）', review.area_owners, '@');

                return html || '<p class="text-tertiary">未返回结构化反馈</p>';
            } catch (e) {
                return `<p style="color: var(--signal-red);">渲染失败：${this.esc(e.message)}</p>`;
            }
        },
    };
}
