// community.js - Community Pulse 视图

function communityMixin() {
    return {
        // ===== Label suggestion state =====
        labelLoading: null,  // issue.number being analyzed
        labelResult: {},     // {issue_number: [labels]}

        async loadAreas() {
            try {
                this.areas = await this.api('/api/community/areas');
            } catch (e) {
                this.showToast('加载领域失败', e.message, 'error');
            }
        },

        async loadCommunityData() {
            this.communityPage = 1;
            this.communityLoadingMore = false;
            try {
                const params = new URLSearchParams();
                params.set('sort_by', this.sortBy);
                params.set('limit', '200');
                const data = await this.api('/api/community/items?' + params);
                const items = data.items || data;
                this.issues = items.filter(x => x.type === 'issue');
                this.prs = items.filter(x => x.type === 'pr');
                this.stats = {
                    totalIssues: this.issues.length,
                    totalPRs: this.prs.length,
                };
            } catch (e) {
                this.showToast('加载社区动态失败', e.message, 'error');
            }
        },

        async forceRefresh() {
            try {
                const params = new URLSearchParams({ force_refresh: 'true' });
                await this.api('/api/community/items?' + params);
                this.showToast('已触发同步', '后台同步已启动，几秒后刷新查看最新数据', 'success');
            } catch (e) {
                this.showToast('触发刷新失败', e.message, 'error');
            }
        },

        // ===== 内联标签建议（popover）=====
        async toggleLabelPopover(issue, event) {
            // 已加载 -> 关闭
            if (this.labelResult[issue.number]) {
                delete this.labelResult[issue.number];
                return;
            }
            // 关闭其他，打开当前
            this.labelResult = {};
            this.labelLoading = issue.number;
            try {
                const result = await this.api('/api/ai-assistant/suggest-labels', {
                    method: 'POST',
                    body: JSON.stringify({
                        issue_title: issue.title,
                        issue_body: (issue.body || '').slice(0, 2000),
                    }),
                });
                this.labelResult[issue.number] = result.suggested_labels || [];
                if (this.labelResult[issue.number].length === 0) {
                    this.showToast('无标签建议', 'AI 未给出建议（检查 OPENAI_API_KEY 配置）', 'info');
                }
            } catch (e) {
                this.showToast('标签推荐失败', e.message, 'error');
                this.labelResult[issue.number] = [];
            } finally {
                this.labelLoading = null;
            }
        },

        // ===== 点击社区动态的 PR/Issue 弹窗 =====
        // Item 模型的 PR 字段是 number，统一转成 pr_number 供 openPR 使用
        openCommunityPR(pr) {
            return this.openPR({ ...pr, pr_number: pr.number });
        },

        openCommunityIssue(issue) {
            return this.openIssue(issue);
        },

        // ===== Issue/PR 状态标签（社区动态用） =====
        issueStateLabel(state) {
            return {'open': '开放', 'closed': '已关闭'}[state] || '开放';
        },

        prStateLabel(state) {
            return {'open': '开放', 'merged': '已合并', 'closed': '已关闭'}[state] || '开放';
        },
    };
}
