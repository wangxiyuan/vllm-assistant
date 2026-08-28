<script setup lang="ts">
import { useRulesStore } from '@/stores/rules'
import { useReposStore } from '@/stores/repos'
import { useAppStore } from '@/stores/app'
import Icon from '@/components/common/Icon.vue'

const rulesStore = useRulesStore()
const reposStore = useReposStore()
const appStore = useAppStore()

function repoFullName(cloneUrl: string): string {
  let url = cloneUrl.endsWith('.git') ? cloneUrl.slice(0, -4) : cloneUrl
  url = url.replace(/\/+$/, '')
  const parts = url.split('/')
  if (parts.length >= 2) return `${parts[parts.length - 2]}/${parts[parts.length - 1]}`
  return ''
}

function trackedRepoOptions() {
  return reposStore.repos.filter(r => r.tracked).map(r => ({ value: repoFullName(r.clone_url), label: r.repo }))
}

function toggleInList(list: string[], value: string) {
  const idx = list.indexOf(value)
  if (idx === -1) list.push(value)
  else list.splice(idx, 1)
}

function timeLabel(iso: string | null): string {
  if (!iso) return '未运行'
  return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <Teleport to="body">
    <div v-if="rulesStore.showRulesManager" class="modal-backdrop" @click="rulesStore.closeManager()">
      <div class="modal modal-lg" @click.stop>
        <div class="modal-header">
          <h3>AI 筛选规则</h3>
          <button class="modal-close" @click="rulesStore.closeManager()" title="关闭">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>

        <!-- 列表视图 -->
        <div v-if="rulesStore.editingMode === 'list'" class="modal-body">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-4);">
            <div style="font-size:var(--text-sm);color:var(--text-tertiary);">
              每条规则是一个自然语言筛选要求，AI 定时按规则筛选社区 issue/PR，命中结果在总览页按规则分 tab 展示
            </div>
            <button class="btn btn-primary btn-sm" @click="rulesStore.openCreate()">+ 新建规则</button>
          </div>
          <div class="list">
            <div v-for="rule in rulesStore.rules" :key="rule.id" class="list-item" style="flex-direction:column;align-items:stretch;gap:6px;">
              <div style="display:flex;align-items:center;gap:8px;">
                <label class="checkbox-label" style="flex-shrink:0;" :title="rule.enabled ? '停用' : '启用'">
                  <input type="checkbox" :checked="rule.enabled" @change="rulesStore.toggleEnabled(rule)" />
                </label>
                <span class="item-title">{{ rule.name }}</span>
                <span class="badge">{{ rule.match_count ?? 0 }} 命中</span>
                <span class="badge" :class="rule.item_type === 'both' ? '' : 'badge-area'">
                  {{ rule.item_type === 'both' ? 'PR+Issue' : rule.item_type === 'pr' ? '仅 PR' : '仅 Issue' }}
                </span>
                <span style="margin-left:auto;font-size:11px;color:var(--text-tertiary);flex-shrink:0;">
                  {{ timeLabel(rule.last_run_at) }}
                </span>
              </div>
              <div style="font-size:var(--text-sm);color:var(--text-secondary);line-height:1.5;">{{ rule.prompt }}</div>
              <div v-if="rule.last_error" class="badge badge-danger" style="align-self:flex-start;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" :title="rule.last_error">
                上次失败：{{ rule.last_error }}
              </div>
              <div style="display:flex;gap:8px;">
                <button class="card-action-btn" :disabled="rulesStore.runningRuleIds.has(rule.id)" @click="rulesStore.runRule(rule.id)" title="按当前水位线增量筛选">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10" /><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" /></svg>
                  {{ rulesStore.runningRuleIds.has(rule.id) ? '筛选中…' : '立即筛选' }}
                </button>
                <button class="card-action-btn" :disabled="rulesStore.runningRuleIds.has(rule.id)" @click="rulesStore.runRule(rule.id, true)" title="清空现有命中并重新评估最近 7 天条目">
                  ⟲ 重新评估
                </button>
                <button class="card-action-btn" @click="rulesStore.openEdit(rule)">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                  编辑
                </button>
                <button class="card-action-btn is-danger" @click="rulesStore.deleteRule(rule)">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                  删除
                </button>
              </div>
            </div>
            <div v-if="rulesStore.rules.length === 0 && !rulesStore.loading" class="empty-state is-compact">
              <p>还没有筛选规则</p>
              <p style="font-size:var(--text-sm);color:var(--text-tertiary);">例如：「与我领域相关的 RFC 和设计讨论」「量化方向值得关注的 PR」</p>
            </div>
          </div>
        </div>

        <!-- 编辑视图 -->
        <div v-else class="modal-body">
          <div class="form-group">
            <label class="form-label form-label-required">规则名称（tab 显示名）</label>
            <input type="text" class="input" v-model="rulesStore.ruleForm.name" placeholder="如：量化相关 / RFC 与设计讨论" />
          </div>
          <div class="form-group">
            <label class="form-label form-label-required">筛选要求（自然语言，写给 AI）</label>
            <textarea class="textarea" rows="4" v-model="rulesStore.ruleForm.prompt"
                      placeholder="例：找出与模型量化（FP8/INT8/AWQ/GPTQ）直接相关的 issue 或 PR，重点关注 kernel 实现和精度问题；纯文档改动不要。"></textarea>
          </div>
          <div class="form-group">
            <label class="form-label">条目类型</label>
            <div class="tab-bar tab-bar-sm">
              <button class="tab tab-sm" :class="{ active: rulesStore.ruleForm.item_type === 'both' }" @click="rulesStore.ruleForm.item_type = 'both'">PR + Issue</button>
              <button class="tab tab-sm" :class="{ active: rulesStore.ruleForm.item_type === 'pr' }" @click="rulesStore.ruleForm.item_type = 'pr'">仅 PR</button>
              <button class="tab tab-sm" :class="{ active: rulesStore.ruleForm.item_type === 'issue' }" @click="rulesStore.ruleForm.item_type = 'issue'">仅 Issue</button>
            </div>
          </div>
          <div class="form-group" v-if="trackedRepoOptions().length > 0">
            <label class="form-label">限定仓库（不选 = 全部）</label>
            <div style="display:flex;gap:6px;flex-wrap:wrap;">
              <button v-for="opt in trackedRepoOptions()" :key="opt.value" type="button"
                      class="tab tab-sm" :class="{ active: rulesStore.ruleForm.repos.includes(opt.value) }"
                      @click="toggleInList(rulesStore.ruleForm.repos, opt.value)">
                {{ opt.label }}
              </button>
            </div>
          </div>
          <div class="form-group" v-if="appStore.areas.length > 0">
            <label class="form-label">限定领域（不选 = 全部）</label>
            <div style="display:flex;gap:6px;flex-wrap:wrap;">
              <button v-for="area in appStore.areas" :key="area.id" type="button"
                      class="tab tab-sm" :class="{ active: rulesStore.ruleForm.areas.includes(area.id) }"
                      @click="toggleInList(rulesStore.ruleForm.areas, area.id)">
                {{ area.name }}
              </button>
            </div>
          </div>
          <div class="form-group">
            <label class="checkbox-label">
              <input type="checkbox" v-model="rulesStore.ruleForm.enabled" />
              启用（启用后参与定时筛选，在总览页展示为 tab）
            </label>
          </div>
          <div class="modal-footer" style="padding:0;">
            <button class="btn" @click="rulesStore.backToList()">取消</button>
            <button class="btn btn-primary" :disabled="rulesStore.ruleSaving" @click="rulesStore.saveRule()">
              {{ rulesStore.ruleSaving ? '保存中…' : '保存' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
