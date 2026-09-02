<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'

// 结构化意图表单：替代难编辑的预填模板。
// 用户填字段 → 组件拼好规范提示词 → ChatDrawer 直接发送，用户全程不接触模板。
// 点「直接问 AI」可跳过表单走自由对话。
const props = defineProps<{ intent: string }>()
const emit = defineEmits<{
  (e: 'send', prompt: string): void
  (e: 'dismiss'): void
}>()

const TITLES: Record<string, string> = {
  rule: '创建 AI 筛选规则',
  anatomy: '拆解模型',
  report: '生成洞察报告',
}

// rule / report 需要仓库列表；rule 还要已有规则名（避免重复）
const repos = ref<string[]>([])
const ruleNames = ref<string[]>([])

watch(() => props.intent, async (v) => {
  resetForm()
  if (!v) return
  if (v === 'rule' || v === 'report') {
    try {
      const d: any = await api('/api/repos')
      repos.value = (d.repos || []).map((r: any) => r.repo)
    } catch (_) {}
  }
  if (v === 'rule') {
    try {
      const d: any = await api('/api/rules')
      ruleNames.value = (d.rules || []).map((r: any) => r.name)
    } catch (_) {}
  }
}, { immediate: true })

// ── 字段状态 ──
const ruleFocus = ref('')
const ruleTypes = ref({ pr: true, issue: true, commit: false })
const ruleRepos = ref<string[]>([])

const anatomyModel = ref('')
const anatomyNotes = ref('')

const reportTopic = ref('')
const reportSources = ref<string[]>([])
const reportExtra = ref('')

function resetForm() {
  ruleFocus.value = ''
  ruleTypes.value = { pr: true, issue: true, commit: false }
  ruleRepos.value = []
  anatomyModel.value = ''
  anatomyNotes.value = ''
  reportTopic.value = ''
  reportSources.value = []
  reportExtra.value = ''
}

const sourceOptions = computed(() => [...repos.value, 'academic', 'news'])

const canSend = computed(() => {
  switch (props.intent) {
    case 'rule': return !!ruleFocus.value.trim()
    case 'anatomy': return !!anatomyModel.value.trim()
    case 'report': return !!reportTopic.value.trim()
    default: return false
  }
})

function toggleIn(arr: string[], v: string) {
  const i = arr.indexOf(v)
  if (i >= 0) arr.splice(i, 1)
  else arr.push(v)
}

// 拼提示词：只包含用户填了的字段，固定的执行约定由这里统一注入
function buildPrompt(): string {
  const lines: string[] = []
  switch (props.intent) {
    case 'rule': {
      const types = [
        ruleTypes.value.pr ? 'PR' : '',
        ruleTypes.value.issue ? 'Issue' : '',
        ruleTypes.value.commit ? 'Commit' : '',
      ].filter(Boolean).join(' / ') || 'PR / Issue'
      lines.push('帮我创建一条 AI 筛选规则。')
      lines.push(`关注内容：${ruleFocus.value.trim()}`)
      lines.push(`类型：${types}`)
      lines.push(`仓库：${ruleRepos.value.length ? ruleRepos.value.join('、') : '全部已配置仓库'}`)
      if (ruleNames.value.length) lines.push(`已有规则（避免重复）：${ruleNames.value.join('、')}`)
      lines.push('创建成功后帮我立即触发一轮分诊。')
      break
    }
    case 'anatomy':
      lines.push(`帮我拆解模型：${anatomyModel.value.trim()}。`)
      lines.push('要求：先用 read_local_code 读 docs/model-yaml-spec.md 和 scripts/glm5_next_causal_lm.yaml 参考实现，再从 vLLM 源码定位相关类，按 atomic → composite → assembly 编排 YAML，最后用 import_anatomy_yaml 导入。')
      if (anatomyNotes.value.trim()) lines.push(`补充：${anatomyNotes.value.trim()}`)
      break
    case 'report':
      lines.push('帮我生成一份洞察报告。')
      lines.push(`主题：${reportTopic.value.trim()}`)
      lines.push(`来源：${reportSources.value.length ? reportSources.value.join('、') : '全部可用来源'}`)
      if (reportExtra.value.trim()) lines.push(`额外关注：${reportExtra.value.trim()}`)
      break
  }
  return lines.join('\n')
}

function submit() {
  if (!canSend.value) return
  emit('send', buildPrompt())
}
</script>

<template>
  <div class="intent-form">
    <div class="intent-form-header">
      <span class="intent-form-title">{{ TITLES[intent] || 'AI 助手' }}</span>
      <button class="intent-form-skip" @click="emit('dismiss')">直接问 AI ›</button>
    </div>

    <!-- 规则 -->
    <template v-if="intent === 'rule'">
      <div class="intent-field">
        <label class="intent-label">关注内容 <span class="req">*</span></label>
        <textarea class="textarea" rows="2" v-model="ruleFocus"
                  placeholder="描述什么样的 PR/Issue/Commit 算命中，如：涉及 KV Cache 分配或复用机制的性能优化"></textarea>
      </div>
      <div class="intent-field">
        <label class="intent-label">监控类型</label>
        <div class="intent-chips">
          <button class="chip" :class="{ on: ruleTypes.pr }" @click="ruleTypes.pr = !ruleTypes.pr">PR</button>
          <button class="chip" :class="{ on: ruleTypes.issue }" @click="ruleTypes.issue = !ruleTypes.issue">Issue</button>
          <button class="chip" :class="{ on: ruleTypes.commit }" @click="ruleTypes.commit = !ruleTypes.commit">Commit</button>
        </div>
      </div>
      <div class="intent-field">
        <label class="intent-label">仓库 <span class="hint">不选 = 全部</span></label>
        <div class="intent-chips">
          <button v-for="r in repos" :key="r" class="chip" :class="{ on: ruleRepos.includes(r) }"
                  @click="toggleIn(ruleRepos, r)">{{ r }}</button>
        </div>
      </div>
    </template>

    <!-- 拆解 -->
    <template v-else-if="intent === 'anatomy'">
      <div class="intent-field">
        <label class="intent-label">模型名 <span class="req">*</span></label>
        <input class="input" v-model="anatomyModel" placeholder="如 Qwen3-Next / DeepSeek-V3" />
      </div>
      <div class="intent-field">
        <label class="intent-label">补充说明</label>
        <textarea class="textarea" rows="2" v-model="anatomyNotes" placeholder="可选，如只拆文本部分、重点看 MoE"></textarea>
      </div>
    </template>

    <!-- 报告 -->
    <template v-else-if="intent === 'report'">
      <div class="intent-field">
        <label class="intent-label">主题 <span class="req">*</span></label>
        <textarea class="textarea" rows="2" v-model="reportTopic"
                  placeholder="想了解什么，如：最近两周 MoE 通信优化的进展"></textarea>
      </div>
      <div class="intent-field">
        <label class="intent-label">来源 <span class="hint">不选 = 全部</span></label>
        <div class="intent-chips">
          <button v-for="s in sourceOptions" :key="s" class="chip" :class="{ on: reportSources.includes(s) }"
                  @click="toggleIn(reportSources, s)">{{ s }}</button>
        </div>
      </div>
      <div class="intent-field">
        <label class="intent-label">额外关注</label>
        <textarea class="textarea" rows="2" v-model="reportExtra" placeholder="可选"></textarea>
      </div>
    </template>

    <div class="intent-form-footer">
      <button class="btn btn-sm" @click="emit('dismiss')">取消</button>
      <button class="btn btn-primary btn-sm" :disabled="!canSend" @click="submit()">发送给 AI</button>
    </div>
  </div>
</template>

<style scoped>
.intent-form {
  flex-shrink: 0;
  margin: var(--space-4) var(--space-5) 0;
  padding: var(--space-4);
  border: 1px solid var(--border-faint);
  border-radius: var(--radius);
  background: var(--bg-elev-2);
}
.intent-form-header {
  display: flex;
  align-items: center;
  margin-bottom: var(--space-3);
}
.intent-form-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
}
.intent-form-skip {
  margin-left: auto;
  border: none;
  background: none;
  color: var(--signal-blue);
  font-size: var(--text-xs);
  cursor: pointer;
  padding: 2px 4px;
}
.intent-form-skip:hover { text-decoration: underline; }
.intent-field {
  margin-bottom: var(--space-3);
}
.intent-field-row {
  display: flex;
  gap: var(--space-3);
}
.intent-field-row .intent-field { flex: 1; }
.intent-label {
  display: block;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  margin-bottom: 4px;
}
.intent-label .req { color: var(--signal-red); }
.intent-label .hint { color: var(--text-quaternary); margin-left: 4px; }
.intent-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip {
  padding: 3px 10px;
  font-size: var(--text-xs);
  border: 1px solid var(--border-faint);
  border-radius: var(--radius-pill);
  background: var(--bg-elev-1);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--t-fast);
}
.chip:hover { border-color: var(--border); }
.chip.on {
  border-color: var(--amber);
  background: var(--amber-glow-soft);
  color: var(--amber-bright);
}
.intent-form-footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
</style>
