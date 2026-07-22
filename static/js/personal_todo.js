// personal_todo.js - 我的任务面板视图

function personalTodoMixin() {
    return {
        // ===== 任务列表 =====
        todoTasks: [],
        todoStats: { by_status: { todo: 0, in_progress: 0, done: 0 }, by_priority: { P0: 0, P1: 0, P2: 0, P3: 0 } },
        todoLoading: false,
        todoFilterStatus: 'all',
        todoFilterPriority: 'all',
        todoSortBy: 'created',
        todoSortOrder: 'desc',

        // ===== 快速添加任务表单 =====
        showAddTaskModal: false,
        newTask: { title: '', description: '', source: 'self', priority: 'P2', area: '', due_date: '', trigger_dedup_check: false },
        newTaskLoading: false,

        // ===== 任务详情抽屉 =====
        selectedTask: null,
        selectedTaskDetails: null,
        taskDrawerLoading: false,
        editingTask: false,
        editTaskForm: {},

        // ===== 去重检查 =====
        dedupLoading: false,
        dedupResult: null,

        // ===== 洞察报告生成（从任务详情触发）=====
        insightGenLoading: false,

        // ===== 优先级配置 =====
        priorities: ['P0', 'P1', 'P2', 'P3'],
        sources: [
            { value: 'self', label: '自己发现' },
            { value: 'team', label: '团队反馈' },
            { value: 'community', label: '社区提出' },
            { value: 'meeting', label: '会议纪要' },
        ],

        // ===== 加载任务列表 =====
        async loadTodoTasks() {
            this.todoLoading = true;
            try {
                const params = new URLSearchParams();
                params.set('status', this.todoFilterStatus);
                params.set('priority', this.todoFilterPriority);
                params.set('sort_by', this.todoSortBy);
                params.set('sort_order', this.todoSortOrder);
                params.set('per_page', '50');
                const data = await this.api('/api/personal-todo/tasks?' + params);
                this.todoTasks = data.tasks || [];
                this.todoStats = data.stats || this.todoStats;
            } catch (e) {
                this.showToast('加载任务失败', e.message, 'error');
            } finally {
                this.todoLoading = false;
            }
        },

        // ===== 创建任务 =====
        async createTask() {
            if (!this.newTask.title.trim()) {
                this.showToast('标题不能为空', '请输入任务标题', 'error');
                return;
            }
            if (this.newTaskLoading) return;
            this.newTaskLoading = true;
            try {
                const payload = { ...this.newTask };
                if (!payload.due_date) delete payload.due_date;
                if (!payload.area) delete payload.area;
                const result = await this.api('/api/personal-todo/tasks', {
                    method: 'POST',
                    body: JSON.stringify(payload),
                }, 120000);
                this.todoTasks.unshift(result);
                // 更新统计
                if (this.todoStats.by_status) this.todoStats.by_status.todo = (this.todoStats.by_status.todo || 0) + 1;
                if (this.todoStats.by_priority) this.todoStats.by_priority[result.priority] = (this.todoStats.by_priority[result.priority] || 0) + 1;
                this.showToast('任务已创建', `#${result.id} ${result.title}`, 'success');
                // 重置表单并关闭弹窗
                this.newTask = { title: '', description: '', source: 'self', priority: 'P2', area: '', due_date: '', trigger_dedup_check: false };
                this.showAddTaskModal = false;
                // 如果有去重结果，显示提示
                if (result.dedup_check_result && result.dedup_check_result.matches && result.dedup_check_result.matches.length > 0) {
                    this.showToast('发现可能重复', `${result.dedup_check_result.matches.length} 个相似 issue/PR`, 'info', 6000);
                }
            } catch (e) {
                this.showToast('创建失败', e.message, 'error');
            } finally {
                this.newTaskLoading = false;
            }
        },

        // ===== 任务详情抽屉 =====
        openTask(task) {
            this.selectedTask = task;
            this.selectedTaskDetails = null;
            this.taskDrawerLoading = false;
            this.editingTask = false;
            this.dedupResult = task.dedup_check_result || null;
            // 加载详情
            this.loadTaskDetails(task.id);
        },

        closeTask() {
            this.selectedTask = null;
            this.selectedTaskDetails = null;
            this.editingTask = false;
            this.dedupResult = null;
        },

        async loadTaskDetails(taskId) {
            this.taskDrawerLoading = true;
            try {
                const details = await this.api(`/api/personal-todo/tasks/${taskId}`);
                this.selectedTaskDetails = details;
                this.dedupResult = details.dedup_check_result || null;
            } catch (e) {
                this.showToast('加载详情失败', e.message, 'error');
            } finally {
                this.taskDrawerLoading = false;
            }
        },

        // ===== 编辑任务 =====
        startEditTask() {
            if (!this.selectedTaskDetails) return;
            this.editTaskForm = { ...this.selectedTaskDetails };
            this.editingTask = true;
        },
        cancelEditTask() {
            this.editingTask = false;
            this.editTaskForm = {};
        },
        async saveTask() {
            if (!this.selectedTaskDetails) return;
            try {
                const updates = {};
                const fields = ['title', 'description', 'source', 'priority', 'status', 'area', 'due_date', 'related_issue_number', 'related_pr_number', 'related_url'];
                for (const f of fields) {
                    if (this.editTaskForm[f] !== this.selectedTaskDetails[f]) {
                        let val = this.editTaskForm[f];
                        // 空字符串归一为 null，与后端一致
                        if (val === '') val = null;
                        updates[f] = val;
                    }
                }
                if (Object.keys(updates).length === 0) {
                    this.editingTask = false;
                    return;
                }
                const result = await this.api(`/api/personal-todo/tasks/${this.selectedTaskDetails.id}`, {
                    method: 'PUT',
                    body: JSON.stringify(updates),
                });
                this.selectedTaskDetails = result;
                // 更新列表中的对应项
                const idx = this.todoTasks.findIndex(t => t.id === result.id);
                if (idx >= 0) {
                    this.todoTasks[idx] = { ...this.todoTasks[idx], ...result };
                }
                this.editingTask = false;
                this.showToast('已保存', '任务已更新', 'success');
            } catch (e) {
                this.showToast('保存失败', e.message, 'error');
            }
        },

        // ===== 删除任务 =====
        async deleteTask(task) {
            if (!confirm(`确认删除任务 #${task.id} "${task.title}"？`)) return;
            try {
                await this.api(`/api/personal-todo/tasks/${task.id}`, { method: 'DELETE' });
                this.todoTasks = this.todoTasks.filter(t => t.id !== task.id);
                if (this.selectedTaskDetails && this.selectedTaskDetails.id === task.id) {
                    this.closeTask();
                }
                this.showToast('已删除', '任务已删除', 'info');
            } catch (e) {
                this.showToast('删除失败', e.message, 'error');
            }
        },

        // ===== 标记完成 / 恢复未完成 =====
        async toggleTaskDone(task) {
            const isDone = task.status === 'done';
            try {
                const result = await this.api(`/api/personal-todo/tasks/${task.id}`, {
                    method: 'PUT',
                    body: JSON.stringify({ status: isDone ? 'todo' : 'done' }),
                });
                const idx = this.todoTasks.findIndex(t => t.id === task.id);
                if (idx >= 0) {
                    this.todoTasks[idx] = { ...this.todoTasks[idx], ...result };
                }
                if (this.selectedTaskDetails && this.selectedTaskDetails.id === task.id) {
                    this.selectedTaskDetails = result;
                }
                this.showToast(isDone ? '已恢复' : '已完成', isDone ? '任务已恢复为未完成' : '任务已标记为完成', 'success');
            } catch (e) {
                this.showToast('操作失败', e.message, 'error');
            }
        },

        // ===== 去重检查 =====
        async runDedupCheck(task) {
            if (this.dedupLoading) return;
            this.dedupLoading = true;
            try {
                const result = await this.api(`/api/personal-todo/tasks/${task.id}/dedup-check`, {
                    method: 'POST',
                    body: JSON.stringify({ repos: [], check_type: 'hybrid' }),
                }, 120000);
                this.dedupResult = { checked: true, matches: result.results || [] };
                // 更新列表
                const idx = this.todoTasks.findIndex(t => t.id === task.id);
                if (idx >= 0) {
                    this.todoTasks[idx].dedup_check_result = this.dedupResult;
                    this.todoTasks[idx].has_dedup_check = true;
                }
                if (this.selectedTaskDetails && this.selectedTaskDetails.id === task.id) {
                    this.selectedTaskDetails.dedup_check_result = this.dedupResult;
                    this.selectedTaskDetails.has_dedup_check = true;
                }
                const matchCount = (result.results || []).length;
                if (matchCount > 0) {
                    this.showToast('发现可能重复', `${matchCount} 个相似 issue/PR`, 'info', 6000);
                } else {
                    this.showToast('无重复', '未发现相似 issue/PR', 'success');
                }
            } catch (e) {
                this.showToast('去重检查失败', e.message, 'error');
            } finally {
                this.dedupLoading = false;
            }
        },

        // ===== 从任务详情生成洞察报告 =====
        async generateInsightFromTask(task) {
            if (this.insightGenLoading) return;
            this.insightGenLoading = true;
            try {
                const result = await this.api('/api/intelligence/generate', {
                    method: 'POST',
                    body: JSON.stringify({
                        task_id: task.id,
                        sources: ['vllm', 'vllm-ascend', 'sglang', 'academic', 'news'],
                    }),
                }, 30000);
                this.showToast('报告生成中', result.message || '请稍后在洞察面板查看', 'success', 6000);
                // 关闭抽屉，切到洞察面板
                this.closeTask();
                this.switchView('intelligence');
                // 开始轮询
                setTimeout(() => this.pollReportStatus(result.report_id), 3000);
            } catch (e) {
                this.showToast('生成失败', e.message, 'error');
            } finally {
                this.insightGenLoading = false;
            }
        },

        // ===== Kanban 分组 =====
        get tasksByPriority() {
            const groups = { P0: [], P1: [], P2: [], P3: [] };
            for (const t of this.todoTasks) {
                if (t.status === 'done') continue;
                if (groups[t.priority]) groups[t.priority].push(t);
            }
            return groups;
        },

        get todoCount() { return this.todoStats.by_status?.todo || 0; },
        get inProgressCount() { return this.todoStats.by_status?.in_progress || 0; },
        get doneCount() { return this.todoStats.by_status?.done || 0; },

        // ===== 标签辅助 =====
        sourceLabel(source) {
            const map = { self: '自己发现', team: '团队反馈', community: '社区提出', meeting: '会议纪要' };
            return map[source] || source;
        },
        statusLabel(status) {
            const map = { todo: '待处理', in_progress: '进行中', done: '已完成' };
            return map[status] || status;
        },
        // 今天日期（YYYY-MM-DD），用于过期判断
        todayISO() {
            const d = new Date();
            const y = d.getFullYear();
            const m = String(d.getMonth() + 1).padStart(2, '0');
            const day = String(d.getDate()).padStart(2, '0');
            return `${y}-${m}-${day}`;
        },
        priorityClass(priority) {
            return 'priority-' + (priority || 'P2').toLowerCase();
        },
        statusClass(status) {
            return 'status-' + (status || 'todo');
        },

        // ===== 筛选切换 =====
        switchTodoStatusFilter(status) {
            this.todoFilterStatus = status;
            this.loadTodoTasks();
        },
        switchTodoPriorityFilter(priority) {
            this.todoFilterPriority = priority;
            this.loadTodoTasks();
        },
    };
}
