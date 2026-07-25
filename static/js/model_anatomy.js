// model_anatomy.js — 模型拆解 Alpine.js mixin
// 对应 docs/model_anatomy.md

function modelAnatomyMixin() {
    return {
        // ===== 视图切换 =====
        anatomyTab: 'operators',

        // ===== 算子管理 =====
        operators: [],
        operatorsLoading: false,
        operatorFilterCategory: '',
        operatorSearch: '',

        // ===== 算子编辑器 =====
        showOperatorDetail: false,
        selectedOperator: null,
        showOperatorEditor: false,
        operatorEditorMode: 'create',
        operatorForm: {
            id: null,
            name: '',
            display_name: '',
            description: '',
            category: 'other',
            params_schema: '{}',
            input_shape_desc: '',
            output_shape_desc: '',
            vllm_code_refs: '[]',
            tags: [],
            user_id: null,
        },
        operatorTagInput: '',
        operatorParamsSchemaValid: true,
        operatorParamsSchemaError: '',

        // ===== 模型列表 =====
        models: [],
        modelsLoading: false,
        modelSearch: '',

        // ===== 模型详情/编辑器 =====
        selectedModel: null,
        showModelDetail: false,
        modelDetailLoading: false,

        showModelEditor: false,
        modelEditorMode: 'create',
        modelForm: {
            id: null,
            name: '',
            display_name: '',
            description: '',
            architecture: [],
            params_summary: '',
            tags: [],
            user_id: null,
        },
        modelTagInput: '',
        modelFormSnapshot: null,

        // ===== 模型编辑器 =====
        editingArchitecture: [],

        // ===== 分类选项 =====
        operatorCategoryOptions: [],
        modelCategoryOptions: [
            { value: 'dense', label: 'Dense' },
            { value: 'moe', label: 'MoE' },
            { value: 'hybrid', label: 'Hybrid' },
            { value: 'state_space', label: 'State Space' },
            { value: 'other', label: 'Other' },
        ],
        modelFilterCategory: '',

        // ===== 分类管理 =====
        showCategoryManager: false,
        categoryManagerLoading: false,
        categoryList: [],
        editingCategory: null,
        categoryForm: { name: '', display_name: '', description: '', sort_order: 0 },
        categoryFormMode: 'create',

        // ===== 算子管理 API =====
        async loadOperators() {
            this.operatorsLoading = true;
            try {
                const params = new URLSearchParams();
                if (this.operatorFilterCategory) params.set('category', this.operatorFilterCategory);
                if (this.operatorSearch) params.set('search', this.operatorSearch);
                const qs = params.toString();
                const data = await this.api(`/api/anatomy/operators${qs ? '?' + qs : ''}`);
                this.operators = data.operators || [];
            } catch (e) {
                this.showToast('加载算子失败', e.message, 'error');
            } finally {
                this.operatorsLoading = false;
            }
        },

        // ===== 分类管理 API =====
        _categoryColors: ['var(--signal-blue)', 'var(--signal-green)', 'var(--signal-purple)', 'var(--signal-cyan)', 'var(--amber)', 'var(--signal-red)', 'var(--signal-yellow)', 'var(--text-tertiary)'],

        async loadCategories() {
            try {
                const data = await this.api('/api/anatomy/operators/categories');
                const colors = this._categoryColors;
                this.operatorCategoryOptions = (data.categories || []).map((c, i) => ({
                    value: c.name,
                    label: c.display_name,
                    color: colors[i % colors.length],
                }));
            } catch (_) {}
        },

        openCategoryManager() {
            this.showCategoryManager = true;
            this.categoryForm = { name: '', display_name: '', description: '', sort_order: 0 };
            this.categoryFormMode = 'create';
            this.loadCategoryList();
        },

        async loadCategoryList() {
            this.categoryManagerLoading = true;
            try {
                const data = await this.api('/api/anatomy/operators/categories');
                this.categoryList = data.categories || [];
            } catch (_) {
                this.showToast('加载分类失败', '', 'error');
            } finally {
                this.categoryManagerLoading = false;
            }
        },

        openEditCategory(cat) {
            this.categoryFormMode = 'edit';
            this.categoryForm = {
                name: cat.name,
                display_name: cat.display_name,
                description: cat.description || '',
                sort_order: cat.sort_order || 0,
            };
            this.editingCategory = cat;
        },

        async saveCategory() {
            const name = this.categoryForm.name.trim();
            if (!name || !this.categoryForm.display_name.trim()) return;
            try {
                if (this.categoryFormMode === 'create') {
                    await this.api('/api/anatomy/operators/categories', {
                        method: 'POST',
                        body: JSON.stringify(this.categoryForm),
                    });
                } else if (this.editingCategory) {
                    await this.api(`/api/anatomy/operators/categories/${this.editingCategory.id}`, {
                        method: 'PUT',
                        body: JSON.stringify(this.categoryForm),
                    });
                }
                await this.loadCategoryList();
                await this.loadCategories();
                this.categoryForm = { name: '', display_name: '', description: '', sort_order: 0 };
                this.categoryFormMode = 'create';
                this.editingCategory = null;
            } catch (e) {
                this.showToast('保存分类失败', e.message, 'error');
            }
        },

        async moveCategory(cat, direction) {
            // direction: 'up' (sort_order - 1) or 'down' (sort_order + 1)
            const newOrder = cat.sort_order + (direction === 'up' ? -1 : 1);
            try {
                await this.api(`/api/anatomy/operators/categories/${cat.id}`, {
                    method: 'PUT',
                    body: JSON.stringify({ sort_order: newOrder }),
                });
                await this.loadCategoryList();
                await this.loadCategories();
            } catch (e) {
                this.showToast('调整排序失败', e.message, 'error');
            }
        },

        async deleteCategory(cat) {
            if (!confirm(`确定删除分类「${cat.display_name}」？`)) return;
            try {
                await this.api(`/api/anatomy/operators/categories/${cat.id}`, { method: 'DELETE' });
                await this.loadCategoryList();
                await this.loadCategories();
            } catch (e) {
                this.showToast('删除分类失败', e.message, 'error');
            }
        },

        // ===== 算子编辑器 =====
        viewOperatorDetail(op) {
            this.selectedOperator = op;
            this.showOperatorDetail = true;
        },

        closeOperatorDetail() {
            this.showOperatorDetail = false;
            this.selectedOperator = null;
        },

        editFromDetail() {
            if (!this.selectedOperator) return;
            const op = this.selectedOperator;
            this.closeOperatorDetail();
            // 延迟一帧打开编辑弹窗，让详情弹窗先关闭
            setTimeout(() => this.openEditOperator(op), 50);
        },

        openNewOperator() {
            this.operatorEditorMode = 'create';
            this.operatorForm = {
                id: null, name: '', display_name: '', description: '',
                category: 'other', params_schema: '{}',
                input_shape_desc: '', output_shape_desc: '',
                vllm_code_refs: '[]', tags: [], user_id: null,
            };
            this.operatorTagInput = '';
            this.operatorParamsSchemaValid = true;
            this.operatorParamsSchemaError = '';
            this.showOperatorEditor = true;
        },

        openEditOperator(op) {
            this.operatorEditorMode = 'edit';
            this.operatorForm = {
                id: op.id,
                name: op.name || '',
                display_name: op.display_name || '',
                description: op.description || '',
                category: op.category || 'other',
                params_schema: JSON.stringify(op.params_schema || {}, null, 2),
                input_shape_desc: op.input_shape_desc || '',
                output_shape_desc: op.output_shape_desc || '',
                vllm_code_refs: JSON.stringify(op.vllm_code_refs || [], null, 2),
                tags: [...(op.tags || [])],
                user_id: op.user_id || null,
            };
            this.operatorTagInput = '';
            this.operatorParamsSchemaValid = true;
            this.operatorParamsSchemaError = '';
            this.showOperatorEditor = true;
        },

        closeOperatorEditor() {
            this.showOperatorEditor = false;
        },

        addOperatorTag() {
            const t = this.operatorTagInput.trim().toLowerCase();
            if (t && !this.operatorForm.tags.includes(t)) {
                this.operatorForm.tags.push(t);
            }
            this.operatorTagInput = '';
        },

        removeOperatorTag(tag) {
            this.operatorForm.tags = this.operatorForm.tags.filter(t => t !== tag);
        },

        validateParamsSchema() {
            try {
                const val = JSON.parse(this.operatorForm.params_schema);
                this.operatorParamsSchemaValid = true;
                this.operatorParamsSchemaError = '';
                return val;
            } catch (e) {
                this.operatorParamsSchemaValid = false;
                this.operatorParamsSchemaError = e.message || 'Invalid JSON';
                return null;
            }
        },

        async saveOperator() {
            const name = this.operatorForm.name.trim();
            if (!name) {
                this.showToast('算子名称不能为空', '', 'error');
                return;
            }
            const displayName = this.operatorForm.display_name.trim();
            if (!displayName) {
                this.showToast('显示名称不能为空', '', 'error');
                return;
            }

            let parsedSchema = {};
            if (this.operatorForm.params_schema.trim()) {
                const result = this.validateParamsSchema();
                if (!result) return;
                parsedSchema = result;
            }

            let parsedRefs = [];
            if (this.operatorForm.vllm_code_refs.trim()) {
                try {
                    parsedRefs = JSON.parse(this.operatorForm.vllm_code_refs);
                } catch (e) {
                    this.showToast('代码引用 JSON 格式错误', e.message, 'error');
                    return;
                }
            }

            const body = {
                name,
                display_name: displayName,
                description: this.operatorForm.description,
                category: this.operatorForm.category,
                params_schema: parsedSchema,
                input_shape_desc: this.operatorForm.input_shape_desc,
                output_shape_desc: this.operatorForm.output_shape_desc,
                vllm_code_refs: parsedRefs,
                tags: this.operatorForm.tags,
                user_id: this.operatorForm.user_id,
            };

            try {
                if (this.operatorEditorMode === 'create') {
                    await this.api('/api/anatomy/operators', {
                        method: 'POST',
                        body: JSON.stringify(body),
                    });
                    this.showToast('算子已创建', '', 'success');
                } else {
                    await this.api(`/api/anatomy/operators/${this.operatorForm.id}`, {
                        method: 'PUT',
                        body: JSON.stringify(body),
                    });
                    this.showToast('算子已更新', '', 'success');
                }
                this.showOperatorEditor = false;
                await this.loadOperators();
            } catch (e) {
                this.showToast('保存失败', e.message, 'error');
            }
        },

        async deleteOperator(op) {
            if (!confirm(`确定删除算子「${op.display_name}」？此操作不可撤销。`)) return;
            try {
                await this.api(`/api/anatomy/operators/${op.id}`, { method: 'DELETE' });
                this.showToast('算子已删除', '', 'success');
                this.closeOperatorDetail();
                await this.loadOperators();
            } catch (e) {
                this.showToast('删除失败', e.message, 'error');
            }
        },

        // ===== 模型管理 API =====
        async loadModels() {
            this.modelsLoading = true;
            try {
                const params = new URLSearchParams();
                if (this.modelSearch) params.set('search', this.modelSearch);
                if (this.modelFilterCategory) params.set('category', this.modelFilterCategory);
                const qs = params.toString();
                const data = await this.api(`/api/anatomy/models${qs ? '?' + qs : ''}`);
                this.models = data.models || [];
            } catch (e) {
                this.showToast('加载模型失败', e.message, 'error');
            } finally {
                this.modelsLoading = false;
            }
        },

        // ===== 模型详情 =====
        async viewModel(model) {
            this.modelDetailLoading = true;
            this.showModelDetail = true;
            this.selectedModel = null;
            this.showModelEditor = false;
            try {
                const data = await this.api(`/api/anatomy/models/${model.id}`);
                this.selectedModel = data;
            } catch (e) {
                this.showToast('加载模型详情失败', e.message, 'error');
                this.showModelDetail = false;
            } finally {
                this.modelDetailLoading = false;
            }
        },

        closeModelDetail() {
            this.showModelDetail = false;
            this.selectedModel = null;
        },

        // ===== 模型编辑器 =====
        openNewModel() {
            this.modelEditorMode = 'create';
            this.modelForm = {
                id: null, name: '', display_name: '', description: '',
                category: 'other', architecture: [], params_summary: '', tags: [], user_id: null,
            };
            this.editingArchitecture = [];
            this._stageIdCounter = 0;
            this.modelTagInput = '';
            this.modelFormSnapshot = null;
            this.showModelEditor = true;
            this.showModelDetail = false;
        },

        openEditModel() {
            if (!this.selectedModel) return;
            this.modelEditorMode = 'edit';
            const arch = this.selectedModel.architecture || [];
            this.modelForm = {
                id: this.selectedModel.id,
                name: this.selectedModel.name || '',
                display_name: this.selectedModel.display_name || '',
                description: this.selectedModel.description || '',
                category: this.selectedModel.category || 'other',
                architecture: JSON.parse(JSON.stringify(arch)),
                params_summary: this.selectedModel.params_summary
                    ? JSON.stringify(this.selectedModel.params_summary, null, 2)
                    : '',
                tags: [...(this.selectedModel.tags || [])],
                user_id: this.selectedModel.user_id || null,
            };
            this.editingArchitecture = JSON.parse(JSON.stringify(arch));
            this.modelTagInput = '';
            this._takeModelFormSnapshot();
            this.showModelEditor = true;
            this.showModelDetail = false;
        },

        closeModelEditor() {
            this.showModelEditor = false;
            this.modelFormSnapshot = null;
        },

        _takeModelFormSnapshot() {
            this.modelFormSnapshot = {
                name: this.modelForm.name,
                display_name: this.modelForm.display_name,
                description: this.modelForm.description,
                tags: [...this.modelForm.tags],
                architecture: JSON.parse(JSON.stringify(this.editingArchitecture)),
            };
        },

        get modelFormDirty() {
            if (!this.modelFormSnapshot) return false;
            const snap = this.modelFormSnapshot;
            return snap.name !== this.modelForm.name
                || snap.display_name !== this.modelForm.display_name
                || snap.description !== this.modelForm.description
                || JSON.stringify(snap.tags) !== JSON.stringify(this.modelForm.tags)
                || JSON.stringify(snap.architecture) !== JSON.stringify(this.editingArchitecture);
        },

        _confirmDiscard() {
            if (this.modelFormDirty) {
                if (!confirm('有未保存的修改，确定要放弃吗？')) return false;
            }
            return true;
        },

        addModelTag() {
            const t = this.modelTagInput.trim().toLowerCase();
            if (t && !this.modelForm.tags.includes(t)) {
                this.modelForm.tags.push(t);
            }
            this.modelTagInput = '';
        },

        removeModelTag(tag) {
            this.modelForm.tags = this.modelForm.tags.filter(t => t !== tag);
        },

        // ===== Architecture 编辑器 =====
        addStage() {
            this.editingArchitecture.push({
                type: 'operator',
                operator_id: null,
                operator_name: '',
                params: {},
                label: '',
                children: [],
                order: this.editingArchitecture.length,
            });
        },

        addRepeatBlock() {
            this.editingArchitecture.push({
                type: 'repeat_block',
                label: '',
                repeat_count: 1,
                contents: [[]],
                order: this.editingArchitecture.length,
            });
        },

        removeStage(index) {
            if (!confirm('确定删除这个阶段？')) return;
            this.editingArchitecture.splice(index, 1);
            this._reorderStages();
        },

        addStageBefore(index) {
            this.editingArchitecture.splice(index, 0, {
                type: 'operator',
                operator_id: null,
                operator_name: '',
                params: {},
                label: '',
                children: [],
                order: this.editingArchitecture.length,
            });
            this._reorderStages();
        },

        addRepeatBlockBefore(index) {
            this.editingArchitecture.splice(index, 0, {
                type: 'repeat_block',
                label: '',
                repeat_count: 1,
                contents: [[]],
                order: this.editingArchitecture.length,
            });
            this._reorderStages();
        },

        moveStageUp(index) {
            if (index <= 0) return;
            const tmp = this.editingArchitecture[index];
            this.editingArchitecture[index] = this.editingArchitecture[index - 1];
            this.editingArchitecture[index - 1] = tmp;
            this._reorderStages();
        },

        moveStageDown(index) {
            if (index >= this.editingArchitecture.length - 1) return;
            const tmp = this.editingArchitecture[index];
            this.editingArchitecture[index] = this.editingArchitecture[index + 1];
            this.editingArchitecture[index + 1] = tmp;
            this._reorderStages();
        },

        _reorderStages() {
            this.editingArchitecture.forEach((s, i) => { s.order = i; });
        },

        // 获取算子对象
        operatorById(id) {
            return this.operators.find(o => o.id === id);
        },

        // 选择算子时更新参数默认值
        onStageOperatorChange(stage) {
            const op = this.operatorById(stage.operator_id);
            if (op) {
                stage.operator_name = op.name;
                const schema = op.params_schema;
                if (schema && schema.properties) {
                    const defaults = {};
                    for (const [key, prop] of Object.entries(schema.properties)) {
                        if (prop.default !== undefined) {
                            defaults[key] = prop.default;
                        }
                    }
                    stage.params = defaults;
                } else {
                    stage.params = {};
                }
            } else {
                stage.operator_name = '';
                stage.params = {};
            }
        },

        // ===== RepeatBlock 子编辑器 =====
        addRepeatBlockContent(repeatBlock) {
            repeatBlock.contents.push([]);
        },

        removeRepeatBlockContent(repeatBlock, contentIndex) {
            if (repeatBlock.contents.length <= 1) return;
            if (!confirm('确定删除这套内容？')) return;
            repeatBlock.contents.splice(contentIndex, 1);
        },

        addStageToContent(repeatBlock, contentIndex) {
            repeatBlock.contents[contentIndex].push({
                type: 'operator',
                operator_id: null,
                operator_name: '',
                params: {},
                label: '',
                children: [],
                order: repeatBlock.contents[contentIndex].length,
            });
        },

        removeStageFromContent(repeatBlock, contentIndex, stageIndex) {
            if (!confirm('确定删除这个算子？')) return;
            repeatBlock.contents[contentIndex].splice(stageIndex, 1);
        },

        // ===== 保存模型 =====
        async saveModel() {
            const name = this.modelForm.name.trim();
            if (!name) {
                this.showToast('模型名称不能为空', '', 'error');
                return;
            }
            const displayName = this.modelForm.display_name.trim();
            if (!displayName) {
                this.showToast('显示名称不能为空', '', 'error');
                return;
            }

            if (this.editingArchitecture.length === 0) {
                this.showToast('请至少添加一个阶段', '', 'error');
                return;
            }

            let parsedSummary = {};
            if (this.modelForm.params_summary && this.modelForm.params_summary.trim()) {
                try {
                    parsedSummary = JSON.parse(this.modelForm.params_summary);
                } catch (e) {
                    this.showToast('参数汇总 JSON 格式错误', e.message, 'error');
                    return;
                }
            }

            const body = {
                name,
                display_name: displayName,
                description: this.modelForm.description,
                category: this.modelForm.category || 'other',
                architecture: this.editingArchitecture,
                params_summary: parsedSummary,
                tags: this.modelForm.tags,
                user_id: this.modelForm.user_id,
            };

            try {
                if (this.modelEditorMode === 'create') {
                    await this.api('/api/anatomy/models', {
                        method: 'POST',
                        body: JSON.stringify(body),
                    });
                    this.showToast('模型已创建', '', 'success');
                } else {
                    await this.api(`/api/anatomy/models/${this.modelForm.id}`, {
                        method: 'PUT',
                        body: JSON.stringify(body),
                    });
                    this.showToast('模型已更新', '', 'success');
                }
                this.showModelEditor = false;
                this.modelFormSnapshot = null;
                await this.loadModels();
                if (this.selectedModel && this.selectedModel.id === this.modelForm.id) {
                    await this.viewModel(this.selectedModel);
                }
            } catch (e) {
                this.showToast('保存失败', e.message, 'error');
            }
        },

        async deleteModel(model) {
            if (!confirm(`确定删除模型「${model.display_name}」？此操作不可撤销。`)) return;
            try {
                await this.api(`/api/anatomy/models/${model.id}`, { method: 'DELETE' });
                this.showToast('模型已删除', '', 'success');
                if (this.selectedModel && this.selectedModel.id === model.id) {
                    this.closeModelDetail();
                }
                await this.loadModels();
            } catch (e) {
                this.showToast('删除失败', e.message, 'error');
            }
        },

        // ===== 视图切换钩子 =====
        switchAnatomyTab(tab) {
            this.anatomyTab = tab;
            if (tab === 'operators') {
                this.loadOperators();
                this.loadCategories();
            } else {
                this.loadModels();
            }
        },

        // ===== 可视化渲染 =====
        // 渲染 architecture 为可视化卡片流程图
        renderArchitectureTree(architecture) {
            if (!architecture || !Array.isArray(architecture)) return '';
            let html = '<div class="arch-flow">';
            for (let i = 0; i < architecture.length; i++) {
                const stage = architecture[i];
                // 箭头连接（除了第一个）
                if (i > 0) {
                    html += '<div class="arch-arrow"><svg width="16" height="24" viewBox="0 0 16 24"><path d="M8 0v18M2 12l6 6 6-6" fill="none" stroke="currentColor" stroke-width="2"/></svg></div>';
                }
                if (stage.type === 'repeat_block') {
                    html += this._renderRepeatBlockCard(stage);
                } else {
                    html += this._renderOperatorCard(stage, false);
                }
            }
            html += '</div>';
            return html;
        },

        // 渲染单个算子卡片
        _renderOperatorCard(stage, isCompact) {
            const opName = stage.operator_name || 'Unknown';
            const label = stage.label || '';
            const params = stage.params || {};
            const paramStr = Object.entries(params)
                .map(([k, v]) => `${k}=${v}`)
                .join(', ');

            let html = '<div class="arch-card arch-operator-card">';
            // 头部
            html += '<div class="arch-card-header">';
            html += `<span class="arch-op-icon">○</span>`;
            html += `<span class="arch-op-name">${this.esc(opName)}</span>`;
            if (label && label !== opName) {
                html += `<span class="arch-op-label">${this.esc(label)}</span>`;
            }
            html += '</div>';

            // 参数
            if (paramStr) {
                html += `<div class="arch-card-body"><span class="arch-params">${this.esc(paramStr)}</span></div>`;
            }

            // 子算子
            if (stage.children && stage.children.length > 0) {
                html += '<div class="arch-children"><div class="arch-children-label">└ 子节点</div>';
                for (const child of stage.children) {
                    if (child.type === 'repeat_block') {
                        html += this._renderRepeatBlockCard(child);
                    } else {
                        html += this._renderOperatorCard(child, true);
                    }
                }
                html += '</div>';
            }

            html += '</div>';
            return html;
        },

        // 渲染重复块卡片
        _renderRepeatBlockCard(stage) {
            const contents = stage.contents || [[]];
            const totalLayers = stage.repeat_count * contents.length;

            let html = '<div class="arch-card arch-repeat-card">';
            // 头部
            html += '<div class="arch-card-header">';
            html += `<span class="arch-repeat-badge">×${stage.repeat_count}</span>`;
            html += `<span class="arch-op-name">${this.esc(stage.label || 'Block')}</span>`;
            html += `<span class="arch-op-label">${totalLayers} 层</span>`;
            html += '</div>';

            // 内容区
            html += '<div class="arch-repeat-contents">';
            for (let ci = 0; ci < contents.length; ci++) {
                if (contents.length > 1) {
                    html += `<div class="arch-content-tab">第 ${ci + 1} 套</div>`;
                }
                for (let si = 0; si < contents[ci].length; si++) {
                    const inner = contents[ci][si];
                    if (si > 0) {
                        html += '<div class="arch-arrow-inline"><svg width="12" height="12" viewBox="0 0 12 12"><path d="M2 6h8M6 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.5"/></svg></div>';
                    }
                    if (inner.type === 'repeat_block') {
                        html += this._renderRepeatBlockCard(inner);
                    } else {
                        html += this._renderOperatorCard(inner, true);
                    }
                }
            }
            html += '</div>';

            html += '</div>';
            return html;
        },

        // 统计模型总层数
        countModelLayers(architecture) {
            if (!architecture) return 0;
            let count = 0;
            for (const stage of architecture) {
                if (stage.type === 'repeat_block') {
                    const contents = stage.contents || [[]];
                    let inner = 0;
                    if (contents[0]) {
                        for (const s of contents[0]) {
                            inner += s.type === 'repeat_block'
                                ? (s.repeat_count * (s.contents?.[0]?.length || 1))
                                : 1;
                        }
                    }
                    count += inner * stage.repeat_count * contents.length;
                } else {
                    count += 1;
                }
            }
            return count;
        },
    };
}

window.modelAnatomyMixin = modelAnatomyMixin;