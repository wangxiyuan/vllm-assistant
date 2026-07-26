// personal_todo.js - 我的任务面板视图

function personalTodoMixin() {
    return {
        // ===== 任务列表 =====
        refSuggestOpen: false,  // 编辑任务时关联引用下拉选择
        todoTasks: [],
        todoStats: { by_status: { todo: 0, in_progress: 0, done: 0 }, by_priority: { P0: 0, P1: 0, P2: 0, P3: 0 } },
        todoLoading: false,
        todoFilterStatus: 'all',
        todoFilterPriority: 'all',
        todoSortBy: 'created',
        todoSortOrder: 'desc',
        todoUseKanban: true,  // 默认卡片视图，允许用户切换

        // ===== 快速添加任务表单 =====
        showAddTaskModal: false,
        newTask: { title: '', description: '', source: 'self', priority: 'P2', area: '', assignee_id: null, due_date: '', related_refs: [], refInput: '', trigger_dedup_check: false },
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
            { value: 'self', label: '主动规划' },
            { value: 'team', label: '产品反馈' },
            { value: 'community', label: '社区反馈' },
        ],

        // ===== 子任务 =====
        subtasks: [],
        subtasksLoading: false,
        showSubtaskForm: false,
        newSubtask: { title: '', priority: 'P2', assignee_id: null, related_refs: [], refInput: '' },
        editingSubtaskId: null,
        editSubtaskForm: {},

        // ===== 加载任务列表 =====
        async loadTodoTasks() {
            this.todoLoading = true;
            try {
                const params = new URLSearchParams();
                params.set('status', this.todoFilterStatus);
                if (this.todoFilterPriority !== 'all') params.set('priority', this.todoFilterPriority);
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
                // 分离前端控制字段，不发送到 API
                const { trigger_dedup_check, refInput, ...payload } = this.newTask;
                if (!payload.due_date) delete payload.due_date;
                if (!payload.area) delete payload.area;
                if (!payload.related_refs || payload.related_refs.length === 0) delete payload.related_refs;
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
                this.newTask = { title: '', description: '', source: 'self', priority: 'P2', area: '', assignee_id: null, due_date: '', related_refs: [], refInput: '', trigger_dedup_check: false };
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
            this.subtasks = [];
            this.showSubtaskForm = false;
            // 加载详情
            this.loadTaskDetails(task.id);
            this.loadSubtasks(task.id);
        },

        closeTask() {
            this.selectedTask = null;
            this.selectedTaskDetails = null;
            this.editingTask = false;
            this.dedupResult = null;
            this.subtasks = [];
            this.showSubtaskForm = false;
            this.newSubtask = { title: '', priority: 'P2', assignee_id: null, related_refs: [], refInput: '' };
        },

        async loadTaskDetails(taskId) {
            if (!taskId) {
                this.showToast('无效任务', '任务ID为空', 'error');
                this.taskDrawerLoading = false;
                return;
            }
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
            // 深拷贝 related_refs，防止编辑时同步修改原始数据
            const details = this.selectedTaskDetails;
            this.editTaskForm = {
                ...details,
                related_refs: details.related_refs ? JSON.parse(JSON.stringify(details.related_refs)) : [],
                tags: details.tags ? [...details.tags] : [],
            };
            this.editingTask = true;
        },
        cancelEditTask() {
            this.editingTask = false;
            this.editTaskForm = {};
        },
        async saveTask() {
            if (!this.selectedTaskDetails) return;
            if (!this.editTaskForm.title || !this.editTaskForm.title.trim()) {
                this.showToast('标题不能为空', '', 'error');
                return;
            }
            try {
                const updates = {};
                const fields = ['title', 'description', 'source', 'priority', 'status', 'area', 'assignee_id', 'due_date', 'related_refs'];
                for (const f of fields) {
                    let oldVal = this.selectedTaskDetails[f];
                    let newVal = this.editTaskForm[f];
                    // 空字符串归一为 null，与后端一致
                    if (newVal === '') newVal = null;
                    // 数组用 JSON 序列化做深度比较，避免引用比较导致漏判
                    const isEqual = Array.isArray(oldVal) && Array.isArray(newVal)
                        ? JSON.stringify(oldVal) === JSON.stringify(newVal)
                        : oldVal === newVal;
                    if (!isEqual) {
                        updates[f] = newVal;
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

        // ===== 删除任务（带撤销）=====
        async deleteTask(task) {
            if (!confirm(`确认删除任务 #${task.id} "${task.title}"？`)) return;
            const backup = { ...task };
            try {
                await this.api(`/api/personal-todo/tasks/${task.id}`, { method: 'DELETE' });
                this.todoTasks = this.todoTasks.filter(t => t.id !== task.id);
                if (this.selectedTaskDetails && this.selectedTaskDetails.id === task.id) {
                    this.closeTask();
                }
                // 提供撤销
                this.showUndoToast('已删除', `#${task.id} ${task.title}`, async () => {
                    try {
                        const result = await this.api('/api/personal-todo/tasks', {
                            method: 'POST',
                            body: JSON.stringify({
                                title: backup.title,
                                description: backup.description,
                                source: backup.source || 'self',
                                priority: backup.priority || 'P2',
                                area: backup.area || '',
                                assignee_id: backup.assignee_id || null,
                                due_date: backup.due_date || '',
                                related_refs: backup.related_refs || [],
                                status: backup.status || 'todo',
                            }),
                        });
                        this.todoTasks.unshift(result);
                        this.showToast('已恢复', `#${result.id} ${result.title}`, 'success');
                        this.loadTodoTasks();
                    } catch (e) {
                        this.showToast('恢复失败', e.message, 'error');
                    }
                }, 10000);
            } catch (e) {
                this.showToast('删除失败', e.message, 'error');
            }
        },

        // ===== 标记完成 / 恢复未完成 =====
        async toggleTaskDone(task) {
            // 已取消的任务点击切换时设为待处理，而不是已完成
            let newStatus;
            if (task.status === 'cancelled') {
                newStatus = 'todo';
            } else {
                newStatus = task.status === 'done' ? 'todo' : 'done';
            }
            try {
                const result = await this.api(`/api/personal-todo/tasks/${task.id}`, {
                    method: 'PUT',
                    body: JSON.stringify({ status: newStatus }),
                });
                const idx = this.todoTasks.findIndex(t => t.id === task.id);
                if (idx >= 0) {
                    this.todoTasks[idx] = { ...this.todoTasks[idx], ...result };
                }
                if (this.selectedTaskDetails && this.selectedTaskDetails.id === task.id) {
                    this.selectedTaskDetails = result;
                }
                const isDone = newStatus === 'done';
                this.showToast(isDone ? '已完成' : '已恢复', isDone ? '任务已标记为完成' : '任务已恢复为未完成', 'success');
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

        // ===== 跳转到洞察面板并打开对应报告 =====
        async openTaskInsight(task) {
            const reportId = task.latest_insight_report_id;
            if (!reportId) {
                this.showToast('暂无报告', '该任务还没有已完成的洞察报告', 'info');
                return;
            }
            // 先切到洞察面板（loadIntelReports 会自动触发）
            this.switchView('intelligence');
            // 等一会让视图切换 + 数据加载完成
            await new Promise(r => setTimeout(r, 500));
            // 找到对应报告并打开
            const report = this.intelReports.find(r => r.id === reportId);
            if (report) {
                this.viewReport(report);
            } else {
                // 列表没有，直接通过 API 加载
                this.viewReport({ id: reportId });
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
                if (t.status === 'done' || t.status === 'cancelled') continue;
                if (groups[t.priority]) groups[t.priority].push(t);
            }
            return groups;
        },

        get todoCount() { return this.todoStats.by_status?.todo || 0; },
        get inProgressCount() { return this.todoStats.by_status?.in_progress || 0; },
        get doneCount() { return this.todoStats.by_status?.done || 0; },

        // ===== 标签辅助 =====
        sourceLabel(source) {
            const map = { self: '主动规划', team: '产品反馈', community: '社区反馈' };
            return map[source] || source;
        },
        statusLabel(status) {
            const map = { todo: '待处理', in_progress: '进行中', done: '已完成', cancelled: '已取消' };
            return map[status] || status;
        },
        // 今天日期（YYYY-MM-DD），用于过期判断。由 nowTick 驱动重算，避免每次调用 new Date()
        _todayCache: null,
        _todayCacheDate: null,
        get todayISO() {
            // 引用 nowTick 让 Alpine 在 tick 时重算
            void this.nowTick;
            const d = new Date();
            const todayKey = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
            if (this._todayCacheDate !== todayKey) {
                const y = d.getFullYear();
                const m = String(d.getMonth() + 1).padStart(2, '0');
                const day = String(d.getDate()).padStart(2, '0');
                this._todayCache = `${y}-${m}-${day}`;
                this._todayCacheDate = todayKey;
            }
            return this._todayCache;
        },
        priorityClass(priority) {
            return 'priority-' + (priority || 'P2').toLowerCase();
        },
        statusClass(status) {
            return 'status-' + (status || 'todo');
        },

        // ===== 关联 issue/PR 辅助 =====
        repoMap: {
            vllm: 'vllm-project/vllm',
            'vllm-ascend': 'vllm-project/vllm-ascend',
        },
        // 解析 repo#number 格式，返回 { repo, number, url } 或 null
        parseRelatedRef(ref) {
            if (!ref || !ref.trim()) return null;
            const m = ref.trim().match(/^(vllm|vllm-ascend)\s*#\s*(\d+)$/i);
            if (!m) return null;
            const repo = m[1].toLowerCase();
            const number = parseInt(m[2], 10);
            const repoPath = this.repoMap[repo] || repo;
            // 先尝试判断是 issue 还是 PR（默认为 issue）
            const url = `https://github.com/${repoPath}/issues/${number}`;
            return { repo, number, url };
        },
        // 根据 related_refs 数组生成跳转链接（取第一个）
        relatedUrl(task) {
            if (!task) return null;
            const refs = task.related_refs || [];
            return refs.length > 0 ? refs[0].url : null;
        },
        // 跳转到关联链接
        openRelatedLink(task) {
            const url = this.relatedUrl(task);
            if (url) window.open(url, '_blank');
        },

        // ===== 关联引用辅助方法 =====
        // 从后端解析用户输入，自动判断是 issue 还是 PR
        async resolveRef(input) {
            if (!input || !input.trim()) return null;
            try {
                return await this.api('/api/personal-todo/resolve-ref', {
                    method: 'POST',
                    body: JSON.stringify({ input: input.trim() }),
                });
            } catch (e) {
                this.showToast('解析失败', e.message, 'error');
                return null;
            }
        },
        // 添加关联引用到目标的 related_refs 数组
        async addRelatedRef(target, input) {
            const ref = await this.resolveRef(input);
            if (!ref) return false;
            if (!target.related_refs) target.related_refs = [];
            target.related_refs.push(ref);
            return true;
        },
        // 删除关联引用
        removeRelatedRef(target, index) {
            if (target.related_refs) {
                target.related_refs.splice(index, 1);
            }
        },

        // ===== 子任务 =====

        async loadSubtasks(taskId) {
            if (!taskId) return;
            this.subtasksLoading = true;
            try {
                const data = await this.api(`/api/personal-todo/tasks/${taskId}/subtasks`);
                this.subtasks = data.subtasks || [];
                return data; // 返回 { subtasks, total, done_count } 用于更新进度
            } catch (e) {
                this.showToast('加载子任务失败', e.message, 'error');
                this.subtasks = [];
            } finally {
                this.subtasksLoading = false;
            }
        },

        async createSubtask() {
            if (!this.newSubtask.title.trim() || !this.selectedTask) return;
            const parentId = this.selectedTask.id;
            try {
                const result = await this.api('/api/personal-todo/tasks', {
                    method: 'POST',
                    body: JSON.stringify({
                        title: this.newSubtask.title.trim(),
                        priority: this.newSubtask.priority,
                        assignee_id: this.newSubtask.assignee_id,
                        related_refs: this.newSubtask.related_refs || [],
                        parent_id: parentId,
                        source: 'self',
                    }),
                });
                this.subtasks.push(result);
                this.newSubtask = { title: '', priority: 'P2', assignee_id: null, related_refs: [], refInput: '' };
                this.showSubtaskForm = false;
                // 更新父任务列表中的子任务计数
                this._updateSubtaskCountOnCard(parentId);
                this.showToast('子任务已创建', result.title, 'success');
            } catch (e) {
                this.showToast('创建子任务失败', e.message, 'error');
            }
        },

        async toggleSubtaskDone(subtask) {
            let newStatus;
            if (subtask.status === 'cancelled') {
                newStatus = 'todo';
            } else {
                newStatus = subtask.status === 'done' ? 'todo' : 'done';
            }
            try {
                const result = await this.api(`/api/personal-todo/tasks/${subtask.id}`, {
                    method: 'PUT',
                    body: JSON.stringify({ status: newStatus }),
                });
                const idx = this.subtasks.findIndex(s => s.id === subtask.id);
                if (idx >= 0) {
                    this.subtasks[idx] = result;
                }
                // 更新父任务的子任务计数
                this._updateSubtaskCountOnCard(this.selectedTask?.id);
                this.showToast(newStatus === 'done' ? '子任务已完成' : '子任务已恢复', result.title, 'success');
            } catch (e) {
                this.showToast('操作失败', e.message, 'error');
            }
        },

        async deleteSubtask(subtask) {
            if (!confirm(`确认删除子任务「${subtask.title}」？`)) return;
            try {
                await this.api(`/api/personal-todo/tasks/${subtask.id}`, { method: 'DELETE' });
                this.subtasks = this.subtasks.filter(s => s.id !== subtask.id);
                this._updateSubtaskCountOnCard(this.selectedTask?.id);
                this.showToast('子任务已删除', '', 'info');
            } catch (e) {
                this.showToast('删除失败', e.message, 'error');
            }
        },

        // ===== 子任务编辑 =====
        startEditSubtask(subtask) {
            this.editingSubtaskId = subtask.id;
            this.editSubtaskForm = {
                ...subtask,
                related_refs: subtask.related_refs ? JSON.parse(JSON.stringify(subtask.related_refs)) : [],
            };
        },
        cancelEditSubtask() {
            this.editingSubtaskId = null;
            this.editSubtaskForm = {};
        },
        async saveSubtask() {
            if (!this.editingSubtaskId) return;
            const subtask = this.subtasks.find(s => s.id === this.editingSubtaskId);
            if (!subtask) return;
            if (!this.editSubtaskForm.title || !this.editSubtaskForm.title.trim()) {
                this.showToast('标题不能为空', '', 'error');
                return;
            }
            try {
                const updates = {};
                const fields = ['title', 'priority', 'source', 'assignee_id', 'status', 'related_refs', 'area'];
                for (const f of fields) {
                    let oldVal = subtask[f];
                    let newVal = this.editSubtaskForm[f];
                    if (newVal === '') newVal = null;
                    const isEqual = Array.isArray(oldVal) && Array.isArray(newVal)
                        ? JSON.stringify(oldVal) === JSON.stringify(newVal)
                        : oldVal === newVal;
                    if (!isEqual) {
                        updates[f] = newVal;
                    }
                }
                if (Object.keys(updates).length === 0) {
                    this.editingSubtaskId = null;
                    return;
                }
                const result = await this.api(`/api/personal-todo/tasks/${subtask.id}`, {
                    method: 'PUT',
                    body: JSON.stringify(updates),
                });
                const idx = this.subtasks.findIndex(s => s.id === subtask.id);
                if (idx >= 0) {
                    this.subtasks[idx] = result;
                }
                this.editingSubtaskId = null;
                this.editSubtaskForm = {};
                this.showToast('子任务已更新', result.title, 'success');
            } catch (e) {
                this.showToast('保存失败', e.message, 'error');
            }
        },

        _updateSubtaskCountOnCard(parentId) {
            if (!parentId) return;
            // 更新列表中的父任务卡片显示（子任务计数靠 to_dict 的 children 关系，需要重新加载整个列表）
            // 简单处理：刷新列表来更新卡片上的计数
            this.loadTodoTasks();
        },

        get subtaskProgress() {
            if (!this.subtasks.length) return 0;
            const done = this.subtasks.filter(s => s.status === 'done').length;
            return done;
        },

        get subtaskProgressText() {
            return `${this.subtaskProgress}/${this.subtasks.length}`;
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
