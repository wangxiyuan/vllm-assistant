<script setup lang="ts">
import { onMounted } from 'vue'
import { useAnatomyStore } from '@/stores/anatomy'
import { useAppStore } from '@/stores/app'
import { useUsersStore } from '@/stores/users'
import ArchitectureDiagram from '@/components/anatomy/ArchitectureDiagram.vue'
import ParamsSummary from '@/components/anatomy/ParamsSummary.vue'

const anatomyStore = useAnatomyStore()
const appStore = useAppStore()
const usersStore = useUsersStore()

onMounted(() => {
  anatomyStore.switchAnatomyTab('operators')
  anatomyStore.loadModels()
})

function removeItem<T>(arr: T[], item: T) {
  const idx = arr.indexOf(item)
  if (idx >= 0) arr.splice(idx, 1)
}

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
  moe: '🧩', dense: '⬛', hybrid: '🔀', state_space: '〰️',
}

function onOperatorClickFromDiagram(operatorId: number) {
  const op = anatomyStore.operators.find(o => o.id === operatorId)
  if (op) {
    anatomyStore.viewOperatorDetail(op, true)
  }
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
      <div class="anatomy-filters">
        <input type="text" class="input" v-model="anatomyStore.operatorSearch" placeholder="搜索算子…" />
        <select class="select" v-model="anatomyStore.operatorFilterCategory">
          <option value="">全部分类</option>
          <option v-for="cat in anatomyStore.operatorCategoryOptions" :key="cat.value" :value="cat.value">{{ cat.label }}</option>
        </select>
        <button class="btn btn-sm" @click="anatomyStore.openCategoryManager()">分类管理</button>
        <button class="btn btn-primary btn-sm" @click="anatomyStore.openNewOperator()">+ 新建算子</button>
      </div>

      <!-- Operators grouped by category -->
      <div v-for="cat in anatomyStore.operatorCategoryOptions" :key="cat.value" class="op-category-group"
           v-show="anatomyStore.operators.filter(o => o.category === cat.value).length > 0"
           :style="'--group-color: ' + (cat.color || 'var(--signal-blue)')">
        <div class="op-category-header">
          <span class="op-category-dot"></span>
          <span class="op-category-name">{{ cat.label }}</span>
          <span class="op-category-count">{{ anatomyStore.operators.filter(o => o.category === cat.value).length }} 个</span>
        </div>
        <div v-for="op in anatomyStore.operators.filter(o => o.category === cat.value)" :key="op.id" class="operator-card" @click="anatomyStore.viewOperatorDetail(op)">
          <div class="op-card-main">
            <div class="op-card-title">
              <span class="op-name">{{ op.display_name }}</span>
              <span class="op-tech-name">{{ op.name }}</span>
              <span v-if="op.user_id" class="badge-assignee" style="margin-left:auto;">{{ usersStore.userName(op.user_id) }}</span>
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
        <div v-if="anatomyStore.operators.filter(o => o.category === cat.value).length === 0 && !anatomyStore.operatorsLoading" class="empty-state" style="padding:16px;">
          <div class="empty-title">暂无算子</div>
          <div class="empty-desc">点击上方「新建算子」创建第一个积木块</div>
        </div>
      </div>
    </template>

    <!-- ============ Models tab (two-column) ============ -->
    <template v-if="anatomyStore.anatomyTab === 'models'">
      <div style="display:flex;gap:16px;">
        <!-- Left: model list -->
        <div style="flex:0 0 320px;">
          <div class="panel">
            <div class="panel-header" style="border-bottom:1px solid var(--border-faint);flex-direction:column;gap:8px;">
              <div class="panel-actions" style="width:100%;">
                <input type="text" class="input input-sm" v-model="anatomyStore.modelSearch" placeholder="搜索模型…" style="width:100%;">
              </div>
              <div class="panel-actions" style="width:100%;">
                <select class="select select-sm" v-model="anatomyStore.modelFilterCategory" style="width:100%;">
                  <option value="">所有架构</option>
                  <option v-for="cat in anatomyStore.modelCategoryOptions" :key="cat.value" :value="cat.value">{{ cat.label }}</option>
                </select>
              </div>
              <div class="panel-actions" style="width:100%;">
                <button class="btn btn-primary btn-sm" style="width:100%;" @click="anatomyStore.openNewModel()">+ 新建模型</button>
              </div>
            </div>
            <div class="panel-body" style="padding:0;max-height:600px;overflow-y:auto;">
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
                    <span>{{ modelIcons[m.category] || '🧱' }}</span>
                  </div>
                  <div class="model-card-body">
                    <div class="model-card-title">
                      <span class="model-name">{{ m.display_name }}</span>
                      <span class="model-tech-name">{{ m.name }}</span>
                      <span v-if="m.user_id" class="badge-assignee" style="margin-left:auto;">{{ usersStore.userName(m.user_id) }}</span>
                    </div>
                    <div class="model-card-meta">
                      <span v-if="m.category && m.category !== 'other'" class="meta-category">{{ m.category }}</span>
                      <span v-if="(m as any).operators_count > 0">{{ (m as any).operators_count }} 种算子</span>
                      <span v-if="m.architecture && m.architecture.length > 0">{{ m.architecture.length }} 个阶段</span>
                      <span>{{ anatomyStore.modelFormSnapshot ? '未保存' : '' }}</span>
                    </div>
                  </div>
                  <svg class="model-card-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Right: model detail / editor -->
        <div style="flex:1;min-width:0;">
          <!-- Empty: no model selected -->
          <div v-if="!anatomyStore.showModelDetail && !anatomyStore.showModelEditor" class="panel">
            <div class="panel-body" style="padding:40px;text-align:center;">
              <div style="font-size:36px;margin-bottom:12px;opacity:0.4;">🧱</div>
              <div style="color:var(--text-tertiary);">从左侧选择一个模型查看详情，或点击「新建模型」开始搭建</div>
            </div>
          </div>

          <!-- Model detail view -->
          <div v-if="anatomyStore.showModelDetail && anatomyStore.selectedModel && !anatomyStore.showModelEditor" class="panel">
            <div class="panel-header">
              <div class="panel-title">
                <span>{{ anatomyStore.selectedModel.display_name }}</span>
                <span class="badge badge-info" style="font-family:var(--font-mono);font-size:10px;margin-left:8px;">{{ anatomyStore.selectedModel.name }}</span>
                <span class="badge" style="margin-left:4px;">{{ anatomyStore.selectedModel.category || 'other' }}</span>
                <span v-if="anatomyStore.selectedModel.user_id" class="badge-assignee" style="margin-left:4px;">{{ usersStore.userName(anatomyStore.selectedModel.user_id) }}</span>
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
            <div v-if="!anatomyStore.modelDetailLoading" class="panel-body" style="padding:16px;">
              <!-- Description -->
              <div v-if="anatomyStore.selectedModel.description" style="margin-bottom:16px;padding:12px;background:var(--bg-secondary);border-radius:6px;color:var(--text-secondary);font-size:13px;line-height:1.6;">
                {{ anatomyStore.selectedModel.description }}
              </div>

              <!-- Params summary -->
              <div v-if="anatomyStore.selectedModel.params_summary && typeof anatomyStore.selectedModel.params_summary === 'object' && Object.keys(anatomyStore.selectedModel.params_summary).length > 0" style="margin-bottom:16px;">
                <div class="section-heading" style="margin-top:0;">参数汇总</div>
                <ParamsSummary :data="anatomyStore.selectedModel.params_summary" />
              </div>

              <!-- Architecture structure -->
              <div style="font-size:13px;">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">
                  <strong>模型结构</strong>
                  <span class="badge">{{ countModelLayers(anatomyStore.selectedModel.architecture) }} 层</span>
                </div>
                <ArchitectureDiagram
                  v-if="anatomyStore.selectedModel.architecture && anatomyStore.selectedModel.architecture.length > 0"
                  :architecture="anatomyStore.selectedModel.architecture"
                  :operators="anatomyStore.operators"
                  @operatorClick="onOperatorClickFromDiagram"
                />
                <div v-else style="padding:24px;text-align:center;color:var(--text-tertiary);font-family:var(--font-mono);font-size:var(--text-sm);">
                  暂无架构数据
                </div>
              </div>

              <!-- Tags -->
              <div v-if="(anatomyStore.selectedModel.tags || []).length > 0" style="margin-top:16px;">
                <span v-for="tag in anatomyStore.selectedModel.tags" :key="tag" class="badge" style="margin-right:4px;">{{ tag }}</span>
              </div>
            </div>
          </div>

          <!-- Model editor -->
          <div v-if="anatomyStore.showModelEditor" class="panel">
            <div class="panel-header">
              <div class="panel-title">
                <span>{{ anatomyStore.modelEditorMode === 'create' ? '新建模型' : '编辑模型' }}</span>
                <span class="badge badge-warning" v-if="anatomyStore.modelFormSnapshot" style="margin-left:8px;">有未保存修改</span>
              </div>
              <div class="panel-actions">
                <button class="btn btn-sm" @click="anatomyStore.closeModelEditor()">取消</button>
                <button class="btn btn-primary btn-sm" @click="anatomyStore.saveModel()" :disabled="!anatomyStore.modelForm.name.trim() || !anatomyStore.modelForm.display_name.trim()">保存</button>
              </div>
            </div>
            <div class="panel-body" style="padding:16px;">
              <!-- Basic info -->
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;">
                <div><label class="form-label form-label-required">模型名称</label><input class="input" type="text" placeholder="如 qwen3.5" v-model="anatomyStore.modelForm.name" style="width:100%;"></div>
                <div><label class="form-label form-label-required">显示名称</label><input class="input" type="text" placeholder="如 通义千问 3.5" v-model="anatomyStore.modelForm.display_name" style="width:100%;"></div>
              </div>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;">
                <div><label class="form-label">架构分类</label>
                  <select class="select" v-model="anatomyStore.modelForm.category" style="width:100%;">
                    <option v-for="cat in anatomyStore.modelCategoryOptions" :key="cat.value" :value="cat.value">{{ cat.label }}</option>
                  </select>
                </div>
                <div><label class="form-label">责任人</label>
                  <select class="select" v-model="anatomyStore.modelForm.user_id" style="width:100%;">
                    <option :value="null">无</option>
                    <option v-for="u in usersStore.users" :key="u.id" :value="u.id">{{ u.name }}</option>
                  </select>
                </div>
              </div>
              <div style="margin-bottom:16px;">
                <label class="form-label">描述</label>
                <textarea class="textarea" placeholder="模型概述" v-model="anatomyStore.modelForm.description" rows="2" style="width:100%;"></textarea>
              </div>

              <!-- Tags -->
              <div style="margin-bottom:16px;">
                <label class="form-label">标签</label>
                <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:4px;">
                  <span v-for="tag in anatomyStore.modelForm.tags" :key="tag" class="badge badge-removable" @click="anatomyStore.removeModelTag(tag)" role="button" tabindex="0">
                    {{ tag }} <span class="badge-remove-icon">&times;</span>
                  </span>
                </div>
                <input class="input input-sm" type="text" placeholder="输入标签后回车" v-model="anatomyStore.modelTagInput" @keydown.enter.prevent="anatomyStore.addModelTag()" style="max-width:200px;">
              </div>

              <!-- Params summary -->
              <div style="margin-bottom:16px;">
                <label class="form-label">参数汇总（JSON）</label>
                <textarea class="textarea textarea-mono" placeholder='{"total_params": "7B", "hidden_size": 4096}' v-model="anatomyStore.modelForm.params_summary" rows="5" style="width:100%;font-family:var(--font-mono);"></textarea>
              </div>

              <!-- Architecture stages editor -->
              <div style="margin-bottom:16px;">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                  <strong>阶段列表</strong>
                  <span class="badge">{{ anatomyStore.editingArchitecture.length }} 个阶段</span>
                  <span style="flex:1;"></span>
                  <button class="btn btn-sm" @click="anatomyStore.addStage()">+ 添加算子</button>
                  <button class="btn btn-sm" @click="anatomyStore.addRepeatBlock()">+ 添加重复块</button>
                </div>
                <div style="background:var(--bg-secondary);border-radius:6px;padding:8px;">
                  <template v-for="(stage, idx) in anatomyStore.editingArchitecture" :key="idx">
                    <!-- Insert bar before this stage -->
                    <div style="display:flex;align-items:center;gap:4px;padding:2px 0;">
                      <div style="flex:1;height:1px;background:var(--border-faint);"></div>
                      <button class="btn btn-xs" @click="anatomyStore.addStageBefore(idx)">+ 算子</button>
                      <button class="btn btn-xs" @click="anatomyStore.addRepeatBlockBefore(idx)">+ 重复块</button>
                    </div>
                    <div style="border:1px solid var(--border-faint);border-radius:4px;margin-bottom:6px;padding:8px;background:var(--bg-primary);">
                      <!-- Stage header -->
                      <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">
                        <span class="badge" style="background:var(--bg-tertiary);color:var(--text-secondary);">#{{ idx + 1 }}</span>
                        <span class="badge" :class="stage.type === 'operator' ? 'badge-info' : 'badge-warning'">{{ stage.type === 'operator' ? '算子' : '重复块' }}</span>
                        <span style="flex:1;"></span>
                        <button class="btn btn-sm btn-ghost" @click="anatomyStore.moveStageUp(idx)" :disabled="idx === 0" title="上移" style="padding:2px;">
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="18 15 12 9 6 15"/></svg>
                        </button>
                        <button class="btn btn-sm btn-ghost" @click="anatomyStore.moveStageDown(idx)" :disabled="idx === anatomyStore.editingArchitecture.length - 1" title="下移" style="padding:2px;">
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                        </button>
                        <button class="card-action-btn is-danger" @click="anatomyStore.removeStage(idx)" title="删除">
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                        </button>
                      </div>

                      <!-- Single operator form -->
                      <template v-if="stage.type === 'operator'">
                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:6px;">
                          <div>
                            <label class="field-label-sm form-label-required">选择算子</label>
                            <select class="select select-sm" v-model="stage.operator_id" @change="anatomyStore.onStageOperatorChange(stage)" style="width:100%;">
                              <option value="">请选择算子…</option>
                              <option v-for="op in anatomyStore.operators" :key="op.id" :value="op.id">{{ op.display_name }} ({{ op.name }})</option>
                            </select>
                          </div>
                          <div>
                            <label class="field-label-sm">标签（可选）</label>
                            <input class="input input-sm" type="text" placeholder="如 Pre-Attention Norm" v-model="stage.label" style="width:100%;">
                          </div>
                        </div>
                        <!-- Dynamic params -->
                        <div v-if="stage.operator_id">
                          <label class="field-label-sm">参数</label>
                          <div style="display:flex;flex-wrap:wrap;gap:6px;">
                            <div v-for="(val, key) in stage.params" :key="key" style="flex:0 0 auto;min-width:120px;">
                              <label style="font-size:10px;color:var(--text-tertiary);display:block;">{{ key }}</label>
                              <input class="input input-sm" :type="typeof val === 'number' ? 'number' : 'text'" :value="val" @input="stage.params[key] = ($event.target as HTMLInputElement).value" style="width:100%;">
                            </div>
                          </div>
                        </div>
                      </template>

                      <!-- Repeat block form -->
                      <template v-if="stage.type === 'repeat_block'">
                        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:6px;">
                          <div>
                            <label class="field-label-sm form-label-required">标签</label>
                            <input class="input input-sm" type="text" placeholder="如 Transformer Layer" v-model="stage.label" style="width:100%;">
                          </div>
                          <div>
                            <label class="field-label-sm form-label-required">重复次数</label>
                            <input class="input input-sm" type="number" min="1" v-model="stage.repeat_count" style="width:100%;">
                          </div>
                          <div>
                            <label class="field-label-sm">套数</label>
                            <div style="display:flex;gap:4px;">
                              <span class="badge">{{ stage.contents.length }} 套</span>
                              <button class="btn btn-sm btn-ghost" @click="anatomyStore.addRepeatBlockContent(stage)" title="添加一套内容" style="padding:2px;">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                              </button>
                            </div>
                          </div>
                        </div>

                        <!-- Content sets -->
                        <template v-for="(contentSet, ci) in stage.contents" :key="ci">
                          <div style="margin-top:8px;border:1px solid var(--border-faint);border-radius:4px;padding:8px;background:var(--bg-primary);">
                            <div style="display:flex;align-items:center;gap:4px;margin-bottom:6px;">
                              <span class="badge" style="background:var(--bg-tertiary);color:var(--text-secondary);">第 {{ (ci as number) + 1 }} 套</span>
                              <span style="flex:1;"></span>
                              <button class="btn btn-sm btn-ghost" @click="anatomyStore.addStageToContent(stage, ci as number)" title="添加算子" style="padding:2px;">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                                添加算子
                              </button>
                              <button class="btn btn-sm btn-ghost" @click="anatomyStore.removeRepeatBlockContent(stage, ci as number)" :disabled="stage.contents.length <= 1" title="删除这套内容" style="padding:2px;color:var(--signal-red);">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                              </button>
                            </div>
                            <template v-for="(innerStage, si) in contentSet" :key="si">
                              <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;padding:4px 6px;background:var(--bg-secondary);border-radius:4px;">
                                <span class="badge" style="background:var(--bg-tertiary);color:var(--text-secondary);font-size:10px;">#{{ (si as number) + 1 }}</span>
                                <select class="select select-sm" v-model="innerStage.operator_id" @change="anatomyStore.onStageOperatorChange(innerStage)" style="flex:1;min-width:0;">
                                  <option value="">选择算子…</option>
                                  <option v-for="op in anatomyStore.operators" :key="op.id" :value="op.id">{{ op.display_name }}</option>
                                </select>
                                <input class="input input-sm" type="text" placeholder="标签" v-model="innerStage.label" style="width:120px;">
                                <button class="btn btn-sm btn-ghost" @click="anatomyStore.removeStageFromContent(stage, ci as number, si as number)" style="padding:2px;color:var(--signal-red);">
                                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                                </button>
                              </div>
                            </template>
                            <div v-if="contentSet.length === 0" style="text-align:center;color:var(--text-tertiary);font-size:11px;padding:8px;">点击「添加算子」添加算子到此套内容</div>
                          </div>
                        </template>
                      </template>
                    </div>
                  </template>

                  <!-- Tail insert bar -->
                  <div v-if="anatomyStore.editingArchitecture.length > 0" style="display:flex;align-items:center;gap:4px;padding:2px 0;">
                    <div style="flex:1;height:1px;background:var(--border-faint);"></div>
                    <button class="btn btn-xs" @click="anatomyStore.addStage()">+ 算子</button>
                    <button class="btn btn-xs" @click="anatomyStore.addRepeatBlock()">+ 重复块</button>
                  </div>

                  <div v-if="anatomyStore.editingArchitecture.length === 0" style="text-align:center;color:var(--text-tertiary);padding:24px;">
                    <div style="font-size:24px;margin-bottom:8px;">🧱</div>
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
              <span class="badge badge-info" style="font-family:var(--font-mono);font-size:10px;margin-left:8px;">{{ anatomyStore.selectedOperator.name }}</span>
              <span class="badge" style="margin-left:4px;font-size:10px;">{{ anatomyStore.selectedOperator.category }}</span>
              <span v-if="anatomyStore.selectedOperator.user_id" class="badge-assignee" style="margin-left:4px;">{{ usersStore.userName(anatomyStore.selectedOperator.user_id) }}</span>
            </h3>
            <button v-if="!anatomyStore.operatorDetailReadOnly" class="btn btn-sm" @click="anatomyStore.editFromDetail()">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
              编辑
            </button>
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
                    <td style="color:var(--signal-cyan);">{{ prop.type || '-' }}</td>
                    <td style="color:var(--text-secondary);">{{ prop.default !== undefined ? prop.default : '-' }}</td>
                    <td style="color:var(--text-secondary);">{{ prop.description || '' }}</td>
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
            <template v-if="anatomyStore.operatorDetailReadOnly">
              <button class="btn" @click="anatomyStore.closeOperatorDetail()">关闭</button>
            </template>
            <template v-else>
              <button class="btn btn-danger" @click="anatomyStore.deleteOperator(anatomyStore.selectedOperator)">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                删除
              </button>
              <button class="btn" @click="anatomyStore.closeOperatorDetail()">关闭</button>
              <button class="btn btn-primary" @click="anatomyStore.editFromDetail()">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                编辑
              </button>
            </template>
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
            <div class="grid-3">
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
              <div class="field">
                <label class="form-label">标签</label>
                <div class="tag-input-row">
                  <span v-for="tag in anatomyStore.operatorForm.tags" :key="tag" class="badge badge-removable" @click="anatomyStore.removeOperatorTag(tag)" role="button" tabindex="0">
                    {{ tag }} <span class="badge-remove-icon">&times;</span>
                  </span>
                </div>
                <input class="input input-sm" type="text" placeholder="回车添加标签" v-model="anatomyStore.operatorTagInput" @keydown.enter.prevent="anatomyStore.addOperatorTag()">
              </div>
            </div>
            <div class="field">
              <label class="form-label">参数 Schema（JSON）</label>
              <textarea class="textarea textarea-mono" v-model="anatomyStore.operatorForm.params_schema" rows="10"></textarea>
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
        <div class="modal" @click.stop style="max-width:600px;">
          <div class="modal-header">
            <h3>管理算子分类</h3>
            <button class="modal-close" @click="anatomyStore.showCategoryManager = false" title="关闭">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
          <div class="modal-body">
            <!-- Add/Edit form -->
            <div class="form-row" style="margin-bottom:var(--space-5);align-items:flex-end;">
              <div class="field" style="flex:1;"><label class="field-label-sm">标识</label><input class="input input-sm" type="text" placeholder="如 attention" v-model="anatomyStore.categoryForm.name"></div>
              <div class="field" style="flex:1;"><label class="field-label-sm">显示名称</label><input class="input input-sm" type="text" placeholder="如 Attention" v-model="anatomyStore.categoryForm.display_name"></div>
              <div class="field" style="flex:0 0 60px;"><label class="field-label-sm">排序</label><input class="input input-sm" type="number" v-model="anatomyStore.categoryForm.sort_order"></div>
              <div class="field" style="flex:0 0 auto;justify-content:flex-end;">
                <button class="btn btn-primary btn-sm" @click="anatomyStore.saveCategory()" :disabled="!anatomyStore.categoryForm.name.trim() || !anatomyStore.categoryForm.display_name.trim()">{{ anatomyStore.categoryFormMode === 'create' ? '添加' : '更新' }}</button>
              </div>
            </div>

            <!-- Category list -->
            <div v-if="anatomyStore.categoryManagerLoading" class="detail-loading is-compact">加载中…</div>
            <div v-if="!anatomyStore.categoryManagerLoading && anatomyStore.categoryList.length === 0" class="empty-state is-compact">暂无分类</div>
            <div v-if="!anatomyStore.categoryManagerLoading && anatomyStore.categoryList.length > 0" class="list">
              <div v-for="(cat, catIdx) in anatomyStore.categoryList" :key="cat.id" class="list-item">
                <div class="item-main">
                  <div class="item-header">
                    <span class="item-title">{{ cat.display_name }}</span>
                    <span class="badge badge-info" style="font-family:var(--font-mono);font-size:10px;">{{ cat.name }}</span>
                  </div>
                  <div class="item-meta">
                    <span v-if="cat.description">{{ cat.description }}</span>
                    <span>排序: {{ cat.sort_order }}</span>
                  </div>
                </div>
                <div class="item-side">
                  <button class="card-action-btn" @click="anatomyStore.moveCategory(cat, 'up')" title="上移" :disabled="catIdx === 0">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="18 15 12 9 6 15"/></svg>
                  </button>
                  <button class="card-action-btn" @click="anatomyStore.moveCategory(cat, 'down')" title="下移" :disabled="catIdx === anatomyStore.categoryList.length - 1">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                  </button>
                  <button class="card-action-btn" @click="anatomyStore.openEditCategory(cat)" title="编辑">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                  </button>
                  <button class="card-action-btn is-danger" @click="anatomyStore.deleteCategory(cat)" title="删除">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                  </button>
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
  </div>
</template>