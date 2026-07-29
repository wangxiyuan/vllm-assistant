<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAnatomyStore } from '@/stores/anatomy'
import { useUsersStore } from '@/stores/users'
import { categoryColor, modelCategoryLabel } from '@/utils/helpers'
import ArchitectureDiagram from '@/components/anatomy/ArchitectureDiagram.vue'
import ParamsSummary from '@/components/anatomy/ParamsSummary.vue'
import ParamsSummaryEditor from '@/components/anatomy/ParamsSummaryEditor.vue'

const anatomyStore = useAnatomyStore()
const usersStore = useUsersStore()

onMounted(() => {
  anatomyStore.switchAnatomyTab('operators')
  anatomyStore.loadModels()
})

function countModelLayers(arch: any[] | undefined): number {
  if (!arch) return 0
  let count = 0
  for (const stage of arch) {
    if (stage.type === 'repeat_block') {
      count += (stage.repeat_count || 1) * (stage.contents?.[0]?.length || 1)
    } else {
      count++
    }
  }
  return count
}

const modelIcons: Record<string, string> = {
  moe: 'puzzle', dense: 'square', hybrid: 'shuffle', state_space: 'wave',
}

function onOperatorClickFromDiagram(operatorId: number) {
  const op = anatomyStore.operators.find(o => o.id === operatorId)
  if (op) {
    anatomyStore.viewOperatorDetail(op, true)
  }
}

function catColor(name: string): string {
  return categoryColor(name)
}

function opsInCategory(catValue: string): any[] {
  return anatomyStore.operators.filter(o => o.category === catValue)
}

function isCatCollapsed(name: string): boolean {
  return anatomyStore.collapsedCategories.has(name)
}

function filteredOperatorsEmpty(): boolean {
  return anatomyStore.operators.length === 0
}

const dragIdx = ref<number | null>(null)
const dragOverIdx = ref<number | null>(null)
const schemaTouched = ref(false)

function onSchemaInput() {
  schemaTouched.value = true
  anatomyStore.validateParamsSchema()
}

function onStageDragStart(idx: number) {
  dragIdx.value = idx
}

function onStageDragOver(idx: number) {
  dragOverIdx.value = idx
}

function onStageDrop(targetIdx: number) {
  if (dragIdx.value === null || dragIdx.value === targetIdx) {
    dragIdx.value = null
    dragOverIdx.value = null
    return
  }
  const arr = anatomyStore.editingArchitecture
  const item = arr.splice(dragIdx.value, 1)[0]
  arr.splice(targetIdx, 0, item)
  arr.forEach((s: any, i: number) => { s.order = i })
  dragIdx.value = null
  dragOverIdx.value = null
}

function onStageDragEnd() {
  dragIdx.value = null
  dragOverIdx.value = null
}

const catDragIdx = ref<number | null>(null)
const catDragOverIdx = ref<number | null>(null)

function onCatDragStart(idx: number) {
  catDragIdx.value = idx
}

function onCatDragOver(idx: number) {
  catDragOverIdx.value = idx
}

function onCatDrop(targetIdx: number) {
  if (catDragIdx.value === null || catDragIdx.value === targetIdx) {
    catDragIdx.value = null
    catDragOverIdx.value = null
    return
  }
  anatomyStore.reorderCategories(catDragIdx.value, targetIdx)
  catDragIdx.value = null
  catDragOverIdx.value = null
}

function onCatDragEnd() {
  catDragIdx.value = null
  catDragOverIdx.value = null
}
</script>

<template>
  <div class="view-container">
    <div class="view-header">
      <h2 class="view-title">模型拆解</h2>
    </div>

    <div class="tab-bar" style="margin-bottom:var(--space-5)">
      <button class="tab" :class="{ active: anatomyStore.anatomyTab === 'operators' }"
              @click="anatomyStore.switchAnatomyTab('operators')">算子 <span class="badge">{{ anatomyStore.operators.length }}</span></button>
      <button class="tab" :class="{ active: anatomyStore.anatomyTab === 'models' }"
              @click="anatomyStore.switchAnatomyTab('models')">模型 <span class="badge">{{ anatomyStore.models.length }}</span></button>
    </div>

    <!-- ============ Operators tab ============ -->
    <template v-if="anatomyStore.anatomyTab === 'operators'">
      <!-- Filter row -->
      <div class="anatomy-filters">
        <input type="text" class="input" v-model="anatomyStore.operatorSearch" placeholder="搜索算子…" />
        <button class="btn btn-sm" @click="anatomyStore.openCategoryManager()">分类管理</button>
        <button class="btn btn-primary btn-sm" @click="anatomyStore.openNewOperator()">+ 新建算子</button>
      </div>

      <!-- Category chip bar -->
      <div class="op-cat-chips">
        <button class="op-cat-chip"
          :class="{ active: !anatomyStore.operatorFilterCategory }"
          @click="anatomyStore.operatorFilterCategory = ''"
          @keydown.enter="anatomyStore.operatorFilterCategory = ''"
          role="button" tabindex="0">
          全部
          <span class="op-cat-chip-count">{{ anatomyStore.operators.length }}</span>
        </button>
        <button v-for="cat in anatomyStore.operatorCategoryOptions" :key="cat.value"
          class="op-cat-chip"
          :class="{ active: anatomyStore.operatorFilterCategory === cat.value }"
          :style="{ '--chip-color': cat.color }"
          @click="anatomyStore.operatorFilterCategory = cat.value"
          @keydown.enter="anatomyStore.operatorFilterCategory = cat.value"
          role="button" tabindex="0">
          <span class="op-cat-chip-dot"></span>
          {{ cat.label }}
          <span class="op-cat-chip-count">{{ opsInCategory(cat.value).length }}</span>
        </button>
      </div>

      <!-- Empty state: no operators at all -->
      <div v-if="filteredOperatorsEmpty() && !anatomyStore.operatorsLoading" class="op-empty-state">
        <div class="op-empty-icon"><Icon name="box" :size="40" /></div>
        <div class="op-empty-title">还没有算子</div>
        <div class="op-empty-desc">创建第一个积木块来开始搭建模型结构</div>
        <button class="btn btn-primary" @click="anatomyStore.openNewOperator()">+ 新建算子</button>
      </div>

      <!-- Operators grouped by category -->
      <div v-for="cat in anatomyStore.operatorCategoryOptions" :key="cat.value" class="op-category-group"
           v-show="opsInCategory(cat.value).length > 0"
           :style="{ '--group-color': catColor(cat.value) }">
        <div class="op-category-header"
             @click="anatomyStore.toggleCategoryCollapse(cat.value)"
             @keydown.enter="anatomyStore.toggleCategoryCollapse(cat.value)"
             role="button" tabindex="0">
          <span class="op-category-chevron" :class="{ collapsed: isCatCollapsed(cat.value) }"><Icon name="chevronRight" :size="10" /></span>
          <span class="op-category-tag">
            <span class="op-category-dot"></span>
            <span class="op-category-name">{{ cat.label }}</span>
          </span>
          <span class="op-category-count">{{ opsInCategory(cat.value).length }}</span>
        </div>
        <div v-show="!isCatCollapsed(cat.value)" class="op-category-body">
          <div v-for="op in opsInCategory(cat.value)" :key="op.id" class="op-card" @click="anatomyStore.viewOperatorDetail(op)">
            <div class="op-card-main">
              <div class="op-card-title">
                <span class="op-name">{{ op.display_name }}</span>
                <span class="op-tech-name">{{ op.name }}</span>
                <span v-if="op.user_id" class="badge-assignee ml-auto">{{ usersStore.userName(op.user_id) }}</span>
              </div>
              <p v-if="op.description" class="op-card-desc">{{ op.description }}</p>
              <div class="op-card-meta">
                <span v-if="op.input_shape_desc" class="shape-badge input">in: {{ op.input_shape_desc }}</span>
                <span v-if="op.output_shape_desc" class="shape-badge output">out: {{ op.output_shape_desc }}</span>
                <span v-for="tag in (op.tags || []).slice(0, 3)" :key="tag" class="tag-badge">{{ tag }}</span>
              </div>
            </div>
            <div class="op-card-actions">
              <button class="card-action-btn" @click.stop="anatomyStore.openEditOperator(op)" title="编辑">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
              </button>
              <button class="card-action-btn is-danger" @click.stop="anatomyStore.deleteOperator(op)" title="删除">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- ============ Models tab (two-column) ============ -->
    <template v-if="anatomyStore.anatomyTab === 'models'">
      <div class="models-layout" :class="{ 'model-list-collapsed': anatomyStore.modelListCollapsed }">
        <!-- Left: model list -->
        <div class="model-list-panel">
          <div class="panel">
            <div class="model-list-header">
              <div class="panel-actions model-list-search-row">
                <input type="text" class="input input-sm w-100" v-model="anatomyStore.modelSearch" placeholder="搜索模型…">
              </div>
              <div class="panel-actions w-100">
                <select class="select select-sm w-100" v-model="anatomyStore.modelFilterCategory">
                  <option value="">所有架构</option>
                  <option v-for="cat in anatomyStore.modelCategoryOptions" :key="cat.value" :value="cat.value">{{ cat.label }}</option>
                </select>
              </div>
              <div class="panel-actions w-100">
                <button class="btn btn-primary btn-sm w-100" @click="anatomyStore.openNewModel()">+ 新建模型</button>
              </div>
            </div>
            <div class="panel-body model-list-body">
              <div v-if="anatomyStore.modelsLoading" class="empty-state" style="padding:24px;"><div class="empty-title">加载中…</div></div>
              <div v-if="!anatomyStore.modelsLoading && anatomyStore.models.length === 0" class="empty-state" style="padding:24px;">
                <div class="empty-icon">∅</div>
                <div class="empty-title">暂无模型</div>
                <div class="empty-desc">点击「新建模型」开始搭建</div>
              </div>
              <div class="model-list-grid">
                <div v-for="m in anatomyStore.models" :key="m.id" class="model-card"
                     :class="{ selected: anatomyStore.selectedModel && anatomyStore.selectedModel.id === m.id }"
                     @click="anatomyStore.viewModel(m)">
                  <div class="model-card-icon">
                    <Icon :name="modelIcons[m.category] || 'box'" :size="18" />
                  </div>
                  <div class="model-card-body">
                    <div class="model-card-title">
                      <span class="model-name">{{ m.display_name }}</span>
                      <span class="model-tech-name">{{ m.name }}</span>
                      <span v-if="m.user_id" class="badge-assignee ml-auto">{{ usersStore.userName(m.user_id) }}</span>
                    </div>
                    <div class="model-card-meta">
                      <span v-if="m.category && m.category !== 'other'" class="meta-category">{{ modelCategoryLabel(m.category) }}</span>
                      <span v-if="(m as any).operators_count > 0">{{ (m as any).operators_count }} 种算子</span>
                      <span v-if="m.architecture && m.architecture.length > 0">{{ countModelLayers(m.architecture) }} 层</span>
                    </div>
                  </div>
                  <svg class="model-card-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Collapse toggle button -->
        <button class="model-list-toggle" @click="anatomyStore.toggleModelListCollapse()" :title="anatomyStore.modelListCollapsed ? '展开列表' : '收起列表'">
          <svg v-if="anatomyStore.modelListCollapsed" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
          <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
        </button>

        <!-- Right: model detail / editor -->
        <div class="model-detail-panel">
          <!-- Empty: no model selected -->
          <div v-if="!anatomyStore.showModelDetail && !anatomyStore.showModelEditor" class="panel">
            <div class="panel-body model-detail-empty">
              <div class="model-detail-empty-icon"><Icon name="box" :size="36" /></div>
              <div class="model-detail-empty-text">从左侧选择一个模型查看详情，或点击「新建模型」开始搭建</div>
            </div>
          </div>

          <!-- Model detail view -->
          <div v-if="anatomyStore.showModelDetail && anatomyStore.selectedModel && !anatomyStore.showModelEditor" class="panel">
            <div class="panel-header">
              <div class="panel-title">
                <span>{{ anatomyStore.selectedModel.display_name }}</span>
                <span class="badge badge-info mono-badge">{{ anatomyStore.selectedModel.name }}</span>
                <span class="badge ml-1">{{ modelCategoryLabel(anatomyStore.selectedModel.category || 'other') }}</span>
                <span v-if="anatomyStore.selectedModel.user_id" class="badge-assignee ml-1">{{ usersStore.userName(anatomyStore.selectedModel.user_id) }}</span>
              </div>
              <div class="panel-actions">
                <button class="btn btn-sm" @click="anatomyStore.openEditModel()">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                  编辑
                </button>
                <button class="btn btn-sm btn-danger" @click="anatomyStore.deleteModel(anatomyStore.selectedModel)">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                  删除
                </button>
              </div>
            </div>
            <div v-if="anatomyStore.modelDetailLoading" class="empty-state"><div class="empty-icon">⟳</div><div class="empty-title">加载中…</div></div>
            <div v-if="!anatomyStore.modelDetailLoading" class="panel-body model-detail-body">
              <!-- Description -->
              <div v-if="anatomyStore.selectedModel.description" class="model-detail-desc">
                {{ anatomyStore.selectedModel.description }}
              </div>

              <!-- Params summary -->
              <div v-if="anatomyStore.selectedModel.params_summary && typeof anatomyStore.selectedModel.params_summary === 'object' && Object.keys(anatomyStore.selectedModel.params_summary).length > 0" class="model-detail-section">
                <div class="section-heading model-detail-heading">参数汇总</div>
                <ParamsSummary :data="anatomyStore.selectedModel.params_summary" />
              </div>

              <!-- Architecture structure -->
              <div class="model-detail-section model-detail-arch">
                <div class="model-detail-arch-header">
                  <div class="section-heading" style="margin:0;">模型结构</div>
                  <span class="badge">{{ countModelLayers(anatomyStore.selectedModel.architecture) }} 层</span>
                </div>
                <ArchitectureDiagram
                  v-if="anatomyStore.selectedModel.architecture && anatomyStore.selectedModel.architecture.length > 0"
                  :architecture="anatomyStore.selectedModel.architecture"
                  :operators="anatomyStore.operators"
                  @operatorClick="onOperatorClickFromDiagram"
                />
                <div v-else class="arch-empty-inline">暂无架构数据</div>
              </div>

              <!-- Tags -->
              <div v-if="(anatomyStore.selectedModel.tags || []).length > 0" class="model-detail-section">
                <div class="section-heading model-detail-heading">标签</div>
                <div class="model-detail-tags">
                  <span v-for="tag in anatomyStore.selectedModel.tags" :key="tag" class="badge">{{ tag }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Model editor -->
          <div v-if="anatomyStore.showModelEditor" class="panel">
            <div class="panel-header">
              <div class="panel-title">
                <span>{{ anatomyStore.modelEditorMode === 'create' ? '新建模型' : '编辑模型' }}</span>
                <span v-if="anatomyStore.modelFormSnapshot" class="badge badge-warning ml-2">有未保存修改</span>
              </div>
              <div class="panel-actions">
                <button class="btn btn-sm" @click="anatomyStore.closeModelEditor()">取消</button>
                <button class="btn btn-primary btn-sm" @click="anatomyStore.saveModel()" :disabled="!anatomyStore.modelForm.name.trim() || !anatomyStore.modelForm.display_name.trim()">保存</button>
              </div>
            </div>
            <div class="panel-body model-editor-body">
              <!-- Basic info -->
              <div class="form-grid-2">
                <div class="field"><label class="form-label form-label-required">模型名称</label><input class="input w-100" type="text" placeholder="如 qwen3.5" v-model="anatomyStore.modelForm.name"></div>
                <div class="field"><label class="form-label form-label-required">显示名称</label><input class="input w-100" type="text" placeholder="如 通义千问 3.5" v-model="anatomyStore.modelForm.display_name"></div>
              </div>
              <div class="form-grid-2">
                <div class="field">
                  <label class="form-label">架构分类</label>
                  <select class="select w-100" v-model="anatomyStore.modelForm.category">
                    <option v-for="cat in anatomyStore.modelCategoryOptions" :key="cat.value" :value="cat.value">{{ cat.label }}</option>
                  </select>
                </div>
                <div class="field">
                  <label class="form-label">责任人</label>
                  <select class="select w-100" v-model="anatomyStore.modelForm.user_id">
                    <option :value="null">无</option>
                    <option v-for="u in usersStore.users" :key="u.id" :value="u.id">{{ u.name }}</option>
                  </select>
                </div>
              </div>
              <div class="field">
                <label class="form-label">描述</label>
                <textarea class="textarea w-100" placeholder="模型概述" v-model="anatomyStore.modelForm.description" rows="2"></textarea>
              </div>

              <!-- Tags -->
              <div class="field">
                <label class="form-label">标签</label>
                <div class="tag-input-row">
                  <span v-for="tag in anatomyStore.modelForm.tags" :key="tag" class="badge badge-removable" @click="anatomyStore.removeModelTag(tag)" role="button" tabindex="0">
                    {{ tag }} <span class="badge-remove-icon">&times;</span>
                  </span>
                </div>
                <input class="input input-sm maxw-200" type="text" placeholder="输入标签后回车" v-model="anatomyStore.modelTagInput" @keydown.enter.prevent="anatomyStore.addModelTag()">
              </div>

              <!-- Params summary editor -->
              <div class="field">
                <label class="form-label">参数汇总</label>
                <ParamsSummaryEditor v-model="anatomyStore.modelForm.params_summary" />
              </div>

              <!-- Architecture stages editor -->
              <div class="field">
                <div class="stage-editor-header">
                  <strong>阶段列表</strong>
                  <span class="badge">{{ anatomyStore.editingArchitecture.length }} 个阶段</span>
                  <span class="flex-1"></span>
                  <button class="btn btn-sm" @click="anatomyStore.addStage()">+ 添加算子</button>
                  <button class="btn btn-sm" @click="anatomyStore.addRepeatBlock()">+ 添加重复块</button>
                </div>
                <div class="stage-editor-container">
                  <template v-for="(stage, idx) in anatomyStore.editingArchitecture" :key="idx">
                    <!-- Hover insert bar before this stage -->
                    <div class="stage-insert-bar">
                      <div class="stage-insert-line"></div>
                      <button class="btn btn-xs stage-insert-btn" @click="anatomyStore.addStageBefore(idx)">+ 算子</button>
                      <button class="btn btn-xs stage-insert-btn" @click="anatomyStore.addRepeatBlockBefore(idx)">+ 重复块</button>
                    </div>
                    <div class="stage-card" draggable="true"
                         @dragstart="onStageDragStart(idx)" @dragover.prevent="onStageDragOver(idx)" @drop.prevent="onStageDrop(idx)" @dragend="onStageDragEnd"
                         :class="{ 'stage-drag-over': dragOverIdx === idx, 'stage-dragging': dragIdx === idx }">
                      <!-- Stage header -->
                      <div class="stage-card-header">
                        <span class="badge stage-badge-num">#{{ idx + 1 }}</span>
                        <span class="badge" :class="stage.type === 'operator' ? 'badge-info' : 'badge-warning'">{{ stage.type === 'operator' ? '算子' : '重复块' }}</span>
                        <span class="stage-drag-handle" title="拖拽排序">
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><circle cx="9" cy="6" r="1.5"/><circle cx="15" cy="6" r="1.5"/><circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/><circle cx="9" cy="18" r="1.5"/><circle cx="15" cy="18" r="1.5"/></svg>
                        </span>
                        <span class="flex-1"></span>
                        <button class="btn btn-sm btn-ghost" @click="anatomyStore.moveStageUp(idx)" :disabled="idx === 0" title="上移">
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="18 15 12 9 6 15"/></svg>
                        </button>
                        <button class="btn btn-sm btn-ghost" @click="anatomyStore.moveStageDown(idx)" :disabled="idx === anatomyStore.editingArchitecture.length - 1" title="下移">
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                        </button>
                        <button class="card-action-btn is-danger" @click="anatomyStore.removeStage(idx)" title="删除">
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                        </button>
                      </div>

                      <!-- Single operator form -->
                      <template v-if="stage.type === 'operator'">
                        <div class="form-grid-2 stage-op-grid">
                          <div>
                            <label class="field-label-sm form-label-required">选择算子</label>
                            <select class="select select-sm w-100" v-model="stage.operator_id" @change="anatomyStore.onStageOperatorChange(stage)">
                              <option value="">请选择算子…</option>
                              <option v-for="op in anatomyStore.operators" :key="op.id" :value="op.id">{{ op.display_name }} ({{ op.name }})</option>
                            </select>
                          </div>
                          <div>
                            <label class="field-label-sm">标签（可选）</label>
                            <input class="input input-sm w-100" type="text" placeholder="如 Pre-Attention Norm" v-model="stage.label">
                          </div>
                        </div>
                        <!-- Dynamic params -->
                        <div v-if="stage.operator_id" class="stage-params">
                          <label class="field-label-sm">参数</label>
                          <div class="stage-params-grid">
                            <div v-for="(val, key) in stage.params" :key="key" class="stage-param-item">
                              <label class="stage-param-label">{{ key }}</label>
                              <input class="input input-sm w-100" :type="typeof val === 'number' ? 'number' : 'text'" :value="val" @input="stage.params[key] = ($event.target as HTMLInputElement).value">
                            </div>
                          </div>
                        </div>
                      </template>

                      <!-- Repeat block form -->
                      <template v-if="stage.type === 'repeat_block'">
                        <div class="form-grid-3 stage-repeat-grid">
                          <div>
                            <label class="field-label-sm form-label-required">标签</label>
                            <input class="input input-sm w-100" type="text" placeholder="如 Transformer Layer" v-model="stage.label">
                          </div>
                          <div>
                            <label class="field-label-sm form-label-required">重复次数</label>
                            <input class="input input-sm w-100" type="number" min="1" v-model="stage.repeat_count">
                          </div>
                          <div>
                            <label class="field-label-sm">套数</label>
                            <div class="stage-content-count">
                              <span class="badge">{{ stage.contents.length }} 套</span>
                              <button class="btn btn-sm btn-ghost" @click="anatomyStore.addRepeatBlockContent(stage)" title="添加一套内容">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                              </button>
                            </div>
                          </div>
                        </div>

                        <!-- Content sets -->
                        <template v-for="(contentSet, ci) in stage.contents" :key="ci">
                          <div class="repeat-content-set">
                            <div class="repeat-content-header">
                              <span class="badge stage-badge-num">第 {{ (ci as number) + 1 }} 套</span>
                              <span class="flex-1"></span>
                              <button class="btn btn-sm btn-ghost" @click="anatomyStore.addStageToContent(stage, ci as number)" title="添加算子">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                                添加算子
                              </button>
                              <button class="btn btn-sm btn-ghost text-red" @click="anatomyStore.removeRepeatBlockContent(stage, ci as number)" :disabled="stage.contents.length <= 1" title="删除这套内容">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                              </button>
                            </div>
                            <template v-for="(innerStage, si) in contentSet" :key="si">
                              <div class="repeat-inner-stage">
                                <span class="badge stage-badge-num-sm">#{{ (si as number) + 1 }}</span>
                                <select class="select select-sm" v-model="innerStage.operator_id" @change="anatomyStore.onStageOperatorChange(innerStage)" style="flex:1;min-width:0;">
                                  <option value="">选择算子…</option>
                                  <option v-for="op in anatomyStore.operators" :key="op.id" :value="op.id">{{ op.display_name }}</option>
                                </select>
                                <input class="input input-sm" type="text" placeholder="标签" v-model="innerStage.label" style="width:120px;">
                                <button class="btn btn-sm btn-ghost text-red" @click="anatomyStore.removeStageFromContent(stage, ci as number, si as number)">
                                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                                </button>
                              </div>
                            </template>
                            <div v-if="contentSet.length === 0" class="repeat-content-empty">点击「添加算子」添加算子到此套内容</div>
                          </div>
                        </template>
                      </template>
                    </div>
                  </template>

                  <!-- Tail insert bar -->
                  <div v-if="anatomyStore.editingArchitecture.length > 0" class="stage-insert-bar">
                    <div class="stage-insert-line"></div>
                    <button class="btn btn-xs stage-insert-btn" @click="anatomyStore.addStage()">+ 算子</button>
                    <button class="btn btn-xs stage-insert-btn" @click="anatomyStore.addRepeatBlock()">+ 重复块</button>
                  </div>

                  <div v-if="anatomyStore.editingArchitecture.length === 0" class="stage-editor-empty">
                    <div class="stage-editor-empty-icon"><Icon name="box" :size="24" /></div>
                    <div>点击「添加算子」或「添加重复块」开始搭建模型结构</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- ============ Operator Detail Modal ============ -->
    <Teleport to="body">
      <div v-if="anatomyStore.showOperatorDetail && anatomyStore.selectedOperator" class="modal-backdrop" @click="anatomyStore.closeOperatorDetail()">
        <div class="modal" @click.stop style="max-width:680px;width:90%;">
          <div class="modal-header">
            <h3>
              <span>{{ anatomyStore.selectedOperator.display_name }}</span>
              <span class="badge badge-info mono-badge">{{ anatomyStore.selectedOperator.name }}</span>
              <span class="badge ml-1" style="font-size:10px;">{{ anatomyStore.selectedOperator.category }}</span>
              <span v-if="anatomyStore.selectedOperator.user_id" class="badge-assignee ml-1">{{ usersStore.userName(anatomyStore.selectedOperator.user_id) }}</span>
            </h3>
            <button class="modal-close" @click="anatomyStore.closeOperatorDetail()" title="关闭">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
          <div class="modal-body form-stack">
            <!-- Description -->
            <div v-if="anatomyStore.selectedOperator.description" class="op-detail-desc">
              {{ anatomyStore.selectedOperator.description }}
            </div>

            <!-- Shape info -->
            <div v-if="anatomyStore.selectedOperator.input_shape_desc || anatomyStore.selectedOperator.output_shape_desc" class="op-detail-shapes">
              <div v-if="anatomyStore.selectedOperator.input_shape_desc" class="op-detail-shape-card input">
                <div class="op-detail-shape-label">输入形状</div>
                <div class="op-detail-shape-value">{{ anatomyStore.selectedOperator.input_shape_desc }}</div>
              </div>
              <div v-if="anatomyStore.selectedOperator.output_shape_desc" class="op-detail-shape-card output">
                <div class="op-detail-shape-label">输出形状</div>
                <div class="op-detail-shape-value">{{ anatomyStore.selectedOperator.output_shape_desc }}</div>
              </div>
            </div>

            <!-- Params schema table -->
            <div v-if="anatomyStore.selectedOperator.params_schema?.properties && Object.keys(anatomyStore.selectedOperator.params_schema.properties).length > 0" class="field">
              <label class="form-label">参数</label>
              <table class="op-params-table">
                <thead>
                  <tr>
                    <th>参数名</th>
                    <th>类型</th>
                    <th>默认值</th>
                    <th>说明</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(prop, pname) in anatomyStore.selectedOperator.params_schema.properties" :key="pname">
                    <td>{{ pname }}</td>
                    <td class="op-param-type">{{ prop.type || '-' }}</td>
                    <td class="op-param-default">{{ prop.default !== undefined ? prop.default : '-' }}</td>
                    <td class="op-param-desc">{{ prop.description || '' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- Code refs -->
            <div v-if="anatomyStore.selectedOperator.vllm_code_refs && anatomyStore.selectedOperator.vllm_code_refs.length > 0" class="field">
              <label class="form-label">vLLM 代码引用</label>
              <div class="op-code-refs">
                <div v-for="(ref, ri) in anatomyStore.selectedOperator.vllm_code_refs" :key="ri" class="op-code-ref">{{ ref }}</div>
              </div>
            </div>

            <!-- Tags -->
            <div v-if="(anatomyStore.selectedOperator.tags || []).length > 0" class="field">
              <label class="form-label">标签</label>
              <div class="op-detail-tags">
                <span v-for="tag in anatomyStore.selectedOperator.tags" :key="tag" class="badge">{{ tag }}</span>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button v-if="!anatomyStore.operatorDetailReadOnly" class="btn btn-danger" @click="anatomyStore.deleteOperator(anatomyStore.selectedOperator)">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
              删除
            </button>
            <span class="flex-1"></span>
            <button class="btn" @click="anatomyStore.closeOperatorDetail()">关闭</button>
            <button class="btn btn-primary" @click="anatomyStore.editFromDetail()">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
              编辑
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ============ Operator Editor Modal ============ -->
    <Teleport to="body">
      <div v-if="anatomyStore.showOperatorEditor" class="modal-backdrop" @click="anatomyStore.closeOperatorEditor()">
        <div class="modal" @click.stop style="max-width:720px;width:90%;">
          <div class="modal-header">
            <h3>{{ anatomyStore.operatorEditorMode === 'create' ? '新建算子' : '编辑算子' }}</h3>
            <button class="modal-close" @click="anatomyStore.closeOperatorEditor()" title="关闭">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
          <div class="modal-body form-stack">
            <div class="grid-2">
              <div class="field"><label class="form-label form-label-required">名称</label><input class="input" type="text" placeholder="如 RMSNorm" v-model="anatomyStore.operatorForm.name"></div>
              <div class="field"><label class="form-label form-label-required">显示名称</label><input class="input" type="text" placeholder="如 RMS 归一化" v-model="anatomyStore.operatorForm.display_name"></div>
            </div>
            <div class="field">
              <label class="form-label">描述</label>
              <textarea class="textarea" placeholder="算子功能描述" v-model="anatomyStore.operatorForm.description" rows="2"></textarea>
            </div>
            <div class="grid-2">
              <div class="field">
                <label class="form-label">分类</label>
                <select class="select" v-model="anatomyStore.operatorForm.category">
                  <option v-for="cat in anatomyStore.operatorCategoryOptions" :key="cat.value" :value="cat.value">{{ cat.label }}</option>
                </select>
              </div>
              <div class="field">
                <label class="form-label">责任人</label>
                <select class="select" v-model="anatomyStore.operatorForm.user_id">
                  <option :value="null">无</option>
                  <option v-for="u in usersStore.users" :key="u.id" :value="u.id">{{ u.name }}</option>
                </select>
              </div>
            </div>
            <div class="field">
              <label class="form-label">标签</label>
              <div class="tag-input-row">
                <span v-for="tag in anatomyStore.operatorForm.tags" :key="tag" class="badge badge-removable" @click="anatomyStore.removeOperatorTag(tag)" role="button" tabindex="0">
                  {{ tag }} <span class="badge-remove-icon">&times;</span>
                </span>
              </div>
              <input class="input input-sm" type="text" placeholder="回车添加标签" v-model="anatomyStore.operatorTagInput" @keydown.enter.prevent="anatomyStore.addOperatorTag()">
            </div>
            <div class="field">
              <label class="form-label">
                参数 Schema（JSON）
                <span v-if="schemaTouched && anatomyStore.operatorParamsSchemaValid" class="schema-badge schema-valid"><Icon name="check" :size="10" /> 格式正确</span>
                <span v-if="schemaTouched && !anatomyStore.operatorParamsSchemaValid" class="schema-badge schema-invalid"><Icon name="x" :size="10" /> 格式错误</span>
              </label>
              <textarea class="textarea textarea-mono" v-model="anatomyStore.operatorForm.params_schema" rows="10" @input="onSchemaInput"></textarea>
              <div v-if="!anatomyStore.operatorParamsSchemaValid" class="form-error">JSON 格式错误: {{ anatomyStore.operatorParamsSchemaError }}</div>
            </div>
            <div class="grid-2">
              <div class="field"><label class="form-label">输入形状</label><input class="input" type="text" placeholder="(batch, seq_len, hidden_size)" v-model="anatomyStore.operatorForm.input_shape_desc"></div>
              <div class="field"><label class="form-label">输出形状</label><input class="input" type="text" placeholder="(batch, seq_len, hidden_size)" v-model="anatomyStore.operatorForm.output_shape_desc"></div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn" @click="anatomyStore.closeOperatorEditor()">取消</button>
            <button class="btn btn-primary" @click="anatomyStore.saveOperator()" :disabled="!anatomyStore.operatorForm.name.trim() || !anatomyStore.operatorForm.display_name.trim()">保存</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ============ Category Manager Modal ============ -->
    <Teleport to="body">
      <div v-if="anatomyStore.showCategoryManager" class="modal-backdrop" @click="anatomyStore.showCategoryManager = false">
        <div class="modal cat-manager-modal" @click.stop>
          <div class="modal-header">
            <h3>管理算子分类</h3>
            <button class="modal-close" @click="anatomyStore.showCategoryManager = false" title="关闭">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
          <div class="modal-body cat-manager-body">
            <!-- Category list -->
            <div class="cat-list-area">
              <div class="cat-list-header">
                <span class="cat-list-title">分类列表</span>
                <span class="cat-list-count">{{ anatomyStore.categoryList.length }} 个</span>
                <span class="flex-1"></span>
                <button class="btn btn-primary btn-xs" @click="anatomyStore.openNewCategory()">+ 新建分类</button>
              </div>
              <div v-if="anatomyStore.categoryManagerLoading" class="cat-list-loading">加载中…</div>
              <div v-if="!anatomyStore.categoryManagerLoading && anatomyStore.categoryList.length === 0" class="cat-list-empty">
                暂无分类，点击右上角「+ 新建分类」
              </div>
              <div v-if="!anatomyStore.categoryManagerLoading && anatomyStore.categoryList.length > 0" class="cat-list-grid">
                <div v-for="(cat, catIdx) in anatomyStore.categoryList" :key="cat.id"
                     class="cat-card"
                     :class="{ 'cat-drag-over': catDragOverIdx === catIdx, 'cat-dragging': catDragIdx === catIdx }"
                     :style="{ '--cat-color': catColor(cat.name) }"
                     draggable="true"
                     @dragstart="onCatDragStart(catIdx)"
                     @dragover.prevent="onCatDragOver(catIdx)"
                     @drop.prevent="onCatDrop(catIdx)"
                     @dragend="onCatDragEnd">
                  <div class="cat-card-color-bar"></div>
                  <div class="cat-card-drag-handle" title="拖拽排序">
                    <svg width="10" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="9" cy="6" r="1.5"/><circle cx="15" cy="6" r="1.5"/><circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/><circle cx="9" cy="18" r="1.5"/><circle cx="15" cy="18" r="1.5"/></svg>
                  </div>
                  <div class="cat-card-body">
                    <div class="cat-card-top">
                      <span class="cat-card-name">{{ cat.display_name }}</span>
                      <span class="cat-card-id mono-badge">{{ cat.name }}</span>
                    </div>
                    <div class="cat-card-bottom">
                      <span v-if="cat.description" class="cat-card-desc">{{ cat.description }}</span>
                    </div>
                  </div>
                  <div class="cat-card-actions">
                    <button class="cat-card-btn" @click="anatomyStore.openEditCategory(cat)" title="编辑">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                    </button>
                    <button class="cat-card-btn cat-card-btn-danger" @click="anatomyStore.deleteCategory(cat)" title="删除">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn" @click="anatomyStore.showCategoryManager = false">关闭</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ============ Category Form Sub-Modal ============ -->
    <Teleport to="body">
      <div v-if="anatomyStore.showCategoryForm" class="modal-backdrop cat-form-backdrop" @click="anatomyStore.cancelEditCategory()">
        <div class="modal cat-form-modal" @click.stop>
          <div class="modal-header">
            <h3>{{ anatomyStore.categoryFormMode === 'create' ? '新建分类' : '编辑分类' }}</h3>
            <button class="modal-close" @click="anatomyStore.cancelEditCategory()" title="关闭">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
          <div class="modal-body form-stack">
            <div class="field">
              <label class="form-label form-label-required">标识</label>
              <input class="input" type="text" placeholder="如 attention" v-model="anatomyStore.categoryForm.name" :disabled="anatomyStore.categoryFormMode === 'edit'">
            </div>
            <div class="field">
              <label class="form-label form-label-required">显示名称</label>
              <input class="input" type="text" placeholder="如 Attention" v-model="anatomyStore.categoryForm.display_name">
            </div>
            <div class="field">
              <label class="form-label">描述</label>
              <input class="input" type="text" placeholder="分类描述（可选）" v-model="anatomyStore.categoryForm.description">
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn" @click="anatomyStore.cancelEditCategory()">取消</button>
            <button class="btn btn-primary" @click="anatomyStore.saveCategory()" :disabled="!anatomyStore.categoryForm.name.trim() || !anatomyStore.categoryForm.display_name.trim()">
              {{ anatomyStore.categoryFormMode === 'create' ? '添加' : '保存修改' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>