// intelligence.js - 洞察面板视图

function intelligenceMixin() {
    return {
        // ===== 报告列表 =====
        intelReports: [],
        intelLoading: false,

        // ===== 生成报告表单 =====
        showIntelModal: false,
        intelForm: {
            task_id: '',
            title: '',
            sources: ['vllm', 'vllm-ascend', 'sglang', 'academic', 'news'],
            excluded_sources: [],
            extra_prompt: '',
        },
        intelGenLoading: false,

        // ===== 任务选择列表（从 personal-todo 加载）=====
        intelTasks: [],

        // ===== 报告查看弹窗 =====
        selectedReport: null,
        reportDetails: null,
        reportModalLoading: false,
        pollingTimer: null,

        // ===== 来源配置 =====
        intelSourceOptions: [
            { value: 'vllm', label: 'vLLM 社区' },
            { value: 'vllm-ascend', label: 'vLLM-Ascend' },
            { value: 'sglang', label: 'sglang' },
            { value: 'academic', label: '学术动态' },
            { value: 'news', label: '新闻动态' },
        ],

        // ===== 加载报告列表 =====
        async loadIntelReports() {
            this.intelLoading = true;
            try {
                const data = await this.api('/api/intelligence/reports');
                this.intelReports = data.reports || [];
            } catch (e) {
                this.showToast('加载报告失败', e.message, 'error');
            } finally {
                this.intelLoading = false;
            }
        },

        // ===== 加载任务列表（供选择关联任务）=====
        async loadIntelTasks() {
            try {
                const params = new URLSearchParams();
                params.set('status', 'all');
                params.set('per_page', '50');
                const data = await this.api('/api/personal-todo/tasks?' + params);
                this.intelTasks = data.tasks || [];
            } catch (_) {
                // 静默失败
            }
        },

        // ===== 切换来源选中 =====
        toggleIntelSource(source) {
            const idx = this.intelForm.sources.indexOf(source);
            if (idx >= 0) {
                this.intelForm.sources.splice(idx, 1);
            } else {
                this.intelForm.sources.push(source);
            }
        },
        isSourceSelected(source) {
            return this.intelForm.sources.includes(source);
        },

        // ===== 生成报告 =====
        async generateReport() {
            if (!this.intelForm.task_id) {
                this.showToast('请选择任务', '关联任务是必填项', 'error');
                return;
            }
            if (this.intelForm.sources.length === 0) {
                this.showToast('请选择来源', '至少选择一个来源', 'error');
                return;
            }
            if (this.intelGenLoading) return;
            this.intelGenLoading = true;
            try {
                const payload = {
                    task_id: parseInt(this.intelForm.task_id, 10),
                    sources: this.intelForm.sources,
                    excluded_sources: this.intelForm.excluded_sources,
                    extra_prompt: this.intelForm.extra_prompt,
                };
                if (this.intelForm.title.trim()) {
                    payload.title = this.intelForm.title.trim();
                }
                const result = await this.api('/api/intelligence/generate', {
                    method: 'POST',
                    body: JSON.stringify(payload),
                }, 30000);
                this.showToast('报告生成中', result.message || '请稍后查看', 'success', 6000);
                // 关闭弹窗
                this.showIntelModal = false;
                // 立即在列表顶部插入一个 generating 状态的项
                this.intelReports.unshift({
                    id: result.report_id,
                    title: result.title,
                    task_id: result.task_id,
                    sources: this.intelForm.sources,
                    created_at: new Date().toISOString(),
                    status: 'generating',
                    word_count: 0,
                });
                // 重置表单（保留 sources 默认勾选）
                this.intelForm.title = '';
                this.intelForm.extra_prompt = '';
                // 开始轮询
                this.pollReportStatus(result.report_id);
            } catch (e) {
                this.showToast('生成失败', e.message, 'error');
            } finally {
                this.intelGenLoading = false;
            }
        },

        // ===== 轮询报告状态 =====
        pollReportStatus(reportId) {
            if (this.pollingTimer) clearInterval(this.pollingTimer);
            const startTime = Date.now();
            const timeout = 600000; // 10 分钟超时（agent 多轮调用耗时较长）
            this.pollingTimer = setInterval(async () => {
                // 用户已离开洞察面板且没在看报告弹窗，停止轮询
                if (this.currentView !== 'intelligence' && !this.selectedReport) {
                    clearInterval(this.pollingTimer);
                    this.pollingTimer = null;
                    return;
                }
                if (Date.now() - startTime > timeout) {
                    clearInterval(this.pollingTimer);
                    this.pollingTimer = null;
                    return;
                }
                try {
                    const report = await this.api(`/api/intelligence/reports/${reportId}`, {}, 10000);
                    // 更新列表中的对应项（不包含 content，避免内存浪费）
                    const idx = this.intelReports.findIndex(r => r.id === reportId);
                    if (idx >= 0) {
                        this.intelReports[idx] = {
                            ...this.intelReports[idx],
                            status: report.status,
                            word_count: report.word_count,
                            error_message: report.error_message,
                            task_title: this.intelReports[idx].task_title,
                        };
                    }
                    // 如果弹窗打开且正在查看该报告，更新弹窗
                    if (this.selectedReport && this.selectedReport.id === reportId) {
                        this.reportDetails = report;
                    }
                    if (report.status === 'completed' || report.status === 'failed') {
                        clearInterval(this.pollingTimer);
                        this.pollingTimer = null;
                        if (report.status === 'completed') {
                            this.showToast('报告已生成', report.title, 'success');
                        } else {
                            this.showToast('报告生成失败', report.error_message || '未知错误', 'error');
                        }
                    }
                } catch (_) {
                    // 静默失败，继续轮询
                }
            }, 3000);
        },

        // ===== 查看报告 =====
        async viewReport(report) {
            this.selectedReport = report;
            this.reportDetails = null;
            this.reportModalLoading = true;
            try {
                this.reportDetails = await this.api(`/api/intelligence/reports/${report.id}`);
            } catch (e) {
                this.showToast('加载报告失败', e.message, 'error');
            } finally {
                this.reportModalLoading = false;
            }
        },

        closeReport() {
            this.selectedReport = null;
            this.reportDetails = null;
        },

        // ===== 删除报告 =====
        async deleteReport(report) {
            if (!confirm(`确认删除报告 "${report.title}"？此操作不可撤销。`)) return;
            try {
                await this.api(`/api/intelligence/reports/${report.id}`, { method: 'DELETE' });
                this.intelReports = this.intelReports.filter(r => r.id !== report.id);
                if (this.selectedReport && this.selectedReport.id === report.id) {
                    this.closeReport();
                }
                this.showToast('已删除', '报告已删除', 'info');
            } catch (e) {
                this.showToast('删除失败', e.message, 'error');
            }
        },

        // ===== 重新生成报告 =====
        async regenerateReport(report) {
            if (!confirm(`确认重新生成报告 "${report.title}"？`)) return;
            try {
                const payload = {
                    task_id: report.task_id,
                    sources: report.sources || ['vllm', 'vllm-ascend', 'sglang', 'academic', 'news'],
                    excluded_sources: report.excluded_sources || [],
                    extra_prompt: report.extra_prompt || '',
                };
                const result = await this.api('/api/intelligence/generate', {
                    method: 'POST',
                    body: JSON.stringify(payload),
                }, 30000);
                this.showToast('重新生成中', result.message, 'success');
                this.intelReports.unshift({
                    id: result.report_id,
                    title: result.title,
                    task_id: result.task_id,
                    sources: payload.sources,
                    created_at: new Date().toISOString(),
                    status: 'generating',
                    word_count: 0,
                });
                this.pollReportStatus(result.report_id);
            } catch (e) {
                this.showToast('重新生成失败', e.message, 'error');
            }
        },

        // ===== 复制 Markdown =====
        copyReportMarkdown(report) {
            if (!this.reportDetails || !this.reportDetails.content) {
                this.showToast('无内容', '报告内容尚未加载', 'error');
                return;
            }
            navigator.clipboard.writeText(this.reportDetails.content).then(() => {
                this.showToast('已复制', 'Markdown 内容已复制到剪贴板', 'success');
            }).catch(() => {
                this.showToast('复制失败', '请手动选择文本复制', 'error');
            });
        },

        // ===== 跳转到任务页面并打开对应任务 =====
        async openTaskFromReport(report) {
            const taskId = report.task_id || (this.reportDetails && this.reportDetails.task_id);
            if (!taskId) {
                this.showToast('无关联任务', '该报告没有关联的任务', 'info');
                return;
            }
            // 关闭报告弹窗
            this.closeReport();
            // 切到任务页面
            this.switchView('personal-todo');
            // 等视图切换完成
            await new Promise(r => setTimeout(r, 500));
            // 找到对应任务并打开
            const task = this.todoTasks.find(t => t.id === taskId);
            if (task) {
                this.openTask(task);
            } else {
                // 列表没有，尝试通过 API 加载详情
                try {
                    const details = await this.api(`/api/personal-todo/tasks/${taskId}`);
                    this.openTask(details);
                } catch (e) {
                    this.showToast('加载任务失败', e.message, 'error');
                }
            }
        },

        // ===== 来源标签 =====
        intelSourceLabel(source) {
            const map = { vllm: 'vLLM', 'vllm-ascend': 'vLLM-Ascend', sglang: 'sglang', academic: '学术', news: '新闻' };
            return map[source] || source;
        },
        intelSourceClass(source) {
            return 'source-' + source;
        },
    };
}
