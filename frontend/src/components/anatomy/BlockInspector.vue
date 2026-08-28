<script setup lang="ts">
/**
 * BlockInspector.vue —— 算子详情（内联右侧面板，非弹窗）
 * 展示选中算子的完整信息：端口、参数、vLLM 引用、composite 子算子。
 */
import { computed } from 'vue'

const props = defineProps<{
  block: any
  blocks: any[]   // 供 composite children 查名
}>()

const emit = defineEmits<{ edit: []; del: [] }>()

const paramRows = computed(() => {
  const p = props.block?.params_schema?.properties || {}
  return Object.entries(p).map(([name, def]) => ({ name, def: def as any }))
})
const formulas = computed(() => props.block?.formula || [])
const ports = computed(() => props.block?.ports || { inputs: [], outputs: [] })
function childBlock(name: string) {
  return props.blocks.find(b => b.name === name)
}
</script>

<template>
  <div class="binsp">
    <div class="binsp-head">
      <div>
        <div class="binsp-title">
          <span class="binsp-mono">{{ block.name }}</span>
          <span class="badge" :class="block.kind === 'atomic' ? 'badge-info' : 'badge-warning'">{{ block.kind }}</span>
        </div>
        <div class="binsp-meta">{{ block.category }}<span v-if="block.file"> · {{ block.file }}</span></div>
      </div>
      <div class="binsp-actions">
        <button class="btn btn-sm" @click="emit('edit')">编辑</button>
        <button class="btn btn-sm btn-danger" @click="emit('del')">删除</button>
      </div>
    </div>

    <p v-if="block.description" class="binsp-desc">{{ block.description }}</p>

    <!-- 计算公式 -->
    <div v-if="formulas.length" class="binsp-section">
      <div class="binsp-section-title">计算公式</div>
      <div class="binsp-formula">
        <div v-for="(f, i) in formulas" :key="i" class="binsp-formula-line">{{ f }}</div>
      </div>
    </div>

    <!-- Ports -->
    <div v-if="ports.inputs.length || ports.outputs.length" class="binsp-section">
      <div class="binsp-section-title">端口</div>
      <div class="binsp-ports-grid">
        <div class="binsp-port-col">
          <div class="binsp-port-col-label is-in">IN</div>
          <div v-for="p in ports.inputs" :key="p.id" class="binsp-port-row is-in">
            <span class="binsp-port-id">{{ p.id }}</span>
            <span class="binsp-port-shape">{{ p.shape || '' }}</span>
            <span class="binsp-port-dtype">{{ p.dtype || '' }}</span>
            <span v-if="p.role" class="binsp-port-role">{{ p.role }}</span>
            <span v-if="p.optional" class="binsp-port-opt">opt</span>
            <span v-if="p.description" class="binsp-port-desc">{{ p.description }}</span>
          </div>
        </div>
        <div class="binsp-port-col">
          <div class="binsp-port-col-label is-out">OUT</div>
          <div v-for="p in ports.outputs" :key="p.id" class="binsp-port-row is-out">
            <span class="binsp-port-id">{{ p.id }}</span>
            <span class="binsp-port-shape">{{ p.shape || '' }}</span>
            <span class="binsp-port-dtype">{{ p.dtype || '' }}</span>
            <span v-if="p.role" class="binsp-port-role">{{ p.role }}</span>
            <span v-if="p.optional" class="binsp-port-opt">opt</span>
            <span v-if="p.description" class="binsp-port-desc">{{ p.description }}</span>
          </div>
        </div>
      </div>
      <div v-if="ports.description" class="binsp-ports-desc">{{ ports.description }}</div>
    </div>

    <!-- Params -->
    <div v-if="paramRows.length" class="binsp-section">
      <div class="binsp-section-title">参数</div>
      <table class="binsp-table">
        <thead><tr><th>参数</th><th>类型</th><th>默认</th><th>来源/说明</th></tr></thead>
        <tbody>
          <tr v-for="r in paramRows" :key="r.name">
            <td>{{ r.name }}</td>
            <td>{{ r.def.type || '-' }}<span v-if="r.def.nullable" class="binsp-badge-src">?</span><span v-if="r.def.items" class="binsp-badge-src">[]</span></td>
            <td>{{ r.def.default !== undefined ? r.def.default : '-' }}</td>
            <td class="binsp-param-src">
              <span v-if="r.def.source" class="binsp-src-chip">config:{{ r.def.source }}</span>
              <span v-if="r.def.parallel" class="binsp-src-chip">parallel:{{ r.def.parallel }}</span>
              <span v-if="r.def.parallel_config" class="binsp-src-chip">pc:{{ r.def.parallel_config }}</span>
              <span v-if="r.def.condition" class="binsp-src-chip cond">if {{ r.def.condition }}</span>
              <span v-if="r.def.description" class="binsp-src-desc">{{ r.def.description }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Composite children with port_bind -->
    <div v-if="block.kind === 'composite' && block.children && block.children.length" class="binsp-section">
      <div class="binsp-section-title">子算子（{{ block.children.length }}）</div>
      <div class="binsp-children">
        <div v-for="c in block.children" :key="c.id" class="binsp-child">
          <span class="binsp-child-id">{{ c.id }}</span>
          <span class="binsp-child-block">{{ c.block }}</span>
          <span v-if="c.as" class="binsp-child-as">as {{ c.as }}</span>
          <span v-if="c.loop" class="binsp-child-loop">×{{ c.loop.count ?? c.loop.label ?? '' }}</span>
          <span v-if="c.kind" class="binsp-child-kind">{{ c.kind }}</span>
          <span v-if="c.condition" class="binsp-child-cond">if {{ c.condition }}</span>
          <span v-if="c.role" class="binsp-child-role">{{ c.role }}</span>
          <div v-if="c.port_bind" class="binsp-child-bind">
            <span v-for="(v, k) in c.port_bind" :key="k" class="binsp-bind-chip">{{ k }}={{ v }}</span>
          </div>
          <div v-if="c.loop?.per_iter_bind" class="binsp-child-bind">
            <span v-for="(v, k) in c.loop.per_iter_bind" :key="k" class="binsp-bind-chip">每轮 {{ k }}={{ v }}</span>
          </div>
          <div v-if="c.note" class="binsp-child-note">{{ c.note }}</div>
        </div>
      </div>
      <div v-if="block.edges && block.edges.length" class="binsp-edges">
        <div v-for="(e,i) in block.edges" :key="i" class="binsp-edge">
          <span class="binsp-edge-from">{{ e.from?.id }}.{{ e.from?.port || '' }}</span>
          <span class="binsp-edge-arrow">→</span>
          <span class="binsp-edge-to">{{ e.to?.id }}.{{ e.to?.port || '' }}</span>
          <span v-if="e.from_segment" class="binsp-edge-seg">[{{ e.from_segment }}]</span>
          <span v-if="e.condition" class="binsp-edge-cond">if {{ e.condition }}</span>
          <span v-if="e.note" class="binsp-edge-note">{{ e.note }}</span>
        </div>
      </div>
      <!-- segments -->
      <div v-if="block.segments && block.segments.length" class="binsp-section-inner">
        <div class="binsp-subtitle">split segments</div>
        <div v-for="s in block.segments" :key="s.name" class="binsp-seg-row">
          <span class="binsp-seg-name">{{ s.name }}</span>
          <span class="binsp-seg-meta">@{{ s.offset }} : {{ s.size }}</span>
          <span class="binsp-seg-src">({{ s.source }})</span>
        </div>
      </div>
    </div>

    <!-- 实现来源：源码文件已并入副标题(binsp-meta)；ops / weights 独立展示 -->
    <div v-if="block.ops && block.ops.length" class="binsp-section">
      <div class="binsp-section-title">内核</div>
      <div class="vllm-ops">{{ block.ops.join(', ') }}</div>
    </div>
    <div v-if="block.weights && block.weights.length" class="binsp-section">
      <div class="binsp-section-title">权重</div>
      <div class="vllm-weights">
        <div v-for="(w,i) in block.weights" :key="i" class="vllm-weight">
          <span class="vllm-w-name">{{ w.name }}</span>
          <span class="vllm-w-shape">{{ w.shape }}</span>
          <span class="vllm-w-loader">{{ w.loader || '' }}</span>
        </div>
      </div>
    </div>

    <div v-if="block.forward_note" class="binsp-section">
      <div class="binsp-section-title">说明</div>
      <div class="binsp-fnote">{{ block.forward_note }}</div>
    </div>

    <!-- Weight prefix note -->
    <div v-if="block.weight_prefix_note" class="binsp-section">
      <div class="binsp-section-title">权重前缀</div>
      <div class="binsp-fnote">{{ block.weight_prefix_note }}</div>
    </div>

    <!-- State -->
    <div v-if="block.state && block.state.length" class="binsp-section">
      <div class="binsp-section-title">状态</div>
      <div v-for="(s,i) in block.state" :key="i" class="binsp-state-row">{{ s.form || '' }}: {{ s.shape || '' }}</div>
    </div>
  </div>
</template>

<style scoped>
.binsp { padding: var(--space-4); }
.binsp-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-3); margin-bottom: var(--space-4); }
.binsp-title { display: flex; align-items: center; gap: var(--space-2); }
.binsp-mono { font-family: var(--font-mono); font-size: 15px; font-weight: 700; color: var(--amber); }
.binsp-meta { font-size: 15px; color: var(--text-tertiary); margin-top: 2px; }
.binsp-actions { display: flex; gap: var(--space-2); }
.binsp-desc { color: var(--text-secondary); font-size: var(--text-sm); margin-bottom: var(--space-4); }
.binsp-formula { display: flex; flex-direction: column; gap: var(--space-1); background: var(--bg-base); border: 1px solid var(--border-faint); border-radius: var(--radius-sm); padding: var(--space-3); }
.binsp-formula-line { font-family: var(--font-mono); font-size: 15px; color: var(--signal-blue, #5aa9e6); white-space: pre-wrap; word-break: break-all; line-height: 1.5; }
.binsp-formula-line::before { content: '▸ '; color: var(--text-tertiary); }
.binsp-section { margin-bottom: var(--space-4); }
.binsp-section-title { font-size: 15px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-tertiary); margin-bottom: var(--space-2); }
.binsp-ports-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); }
.binsp-port-col { background: var(--bg-elev-2); border: 1px solid var(--border-faint); border-radius: var(--radius-sm); padding: var(--space-2); }
.binsp-port-col-label { font-size: 15px; font-weight: 700; margin-bottom: var(--space-1); }
.binsp-port-col-label.is-in { color: var(--signal-blue, #5aa9e6); }
.binsp-port-col-label.is-out { color: var(--signal-green, #7ec8a2); }
.binsp-port-row { display: flex; gap: 6px; font-family: var(--font-mono); font-size: 15px; padding: 2px 0; }
.binsp-port-row.is-in .binsp-port-id { color: var(--signal-blue, #5aa9e6); }
.binsp-port-row.is-out .binsp-port-id { color: var(--signal-green, #7ec8a2); }
.binsp-port-id { font-weight: 600; }
.binsp-port-shape { color: var(--text-secondary); }
.binsp-port-dtype { color: var(--text-tertiary); }
.binsp-table { width: 100%; border-collapse: collapse; font-family: var(--font-mono); font-size: 15px; }
.binsp-table th, .binsp-table td { text-align: left; padding: 4px 6px; border-bottom: 1px solid var(--border-faint); }
.binsp-table th { color: var(--text-tertiary); font-weight: 600; }
.binsp-param-src { color: var(--text-tertiary); }
.binsp-children { display: flex; flex-direction: column; gap: 3px; }
.binsp-child { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; font-family: var(--font-mono); font-size: 15px; padding: 4px 8px; background: var(--bg-elev-2); border: 1px solid var(--border-faint); border-radius: var(--radius-xs); }
.binsp-child-id { color: var(--text-tertiary); }
.binsp-child-block { color: var(--text-primary); font-weight: 600; }
.binsp-child-as { color: var(--text-secondary); }
.binsp-child-loop { color: var(--signal-green, #7ec8a2); font-weight: 700; }
.binsp-child-cond { color: var(--amber); font-size: 15px; }
.binsp-child-role { margin-left: auto; color: var(--text-tertiary); font-size: 15px; }
.binsp-child-note { width: 100%; color: var(--text-tertiary); font-size: 15px; }
.binsp-edges { margin-top: var(--space-2); font-family: var(--font-mono); font-size: 15px; display: flex; flex-direction: column; gap: 2px; }
.binsp-edge-from { color: var(--signal-blue, #5aa9e6); }
.binsp-edge-arrow { color: var(--text-tertiary); }
.binsp-edge-to { color: var(--signal-green, #7ec8a2); }
.binsp-state-row { font-family: var(--font-mono); font-size: 15px; color: var(--text-secondary); }
.binsp-badge-src { color: var(--amber); margin-left: 3px; font-size: 15px; }
.binsp-src-chip { display: inline-block; font-family: var(--font-mono); font-size: 15px; color: var(--signal-blue, #5aa9e6); background: var(--bg-elev-3); padding: 0 5px; border-radius: 3px; margin: 1px 2px 1px 0; }
.binsp-src-chip.cond { color: var(--amber); }
.binsp-src-desc { display: block; color: var(--text-tertiary); font-size: 15px; margin-top: 1px; }
.binsp-child-kind { font-size: 15px; color: var(--text-tertiary); text-transform: uppercase; }
.binsp-child-bind { display: flex; flex-wrap: wrap; gap: 3px; margin-top: 2px; }
.binsp-bind-chip { font-family: var(--font-mono); font-size: 15px; color: var(--text-secondary); background: var(--bg-elev-3); padding: 0 4px; border-radius: 3px; }
.binsp-edge-seg { color: var(--signal-blue, #5aa9e6); margin-left: 4px; font-weight: 600; }
.binsp-edge-cond { color: var(--amber); margin-left: 4px; }
.binsp-edge-note { color: var(--text-tertiary); margin-left: 4px; }
.binsp-section-inner { margin-top: var(--space-2); }
.binsp-subtitle { font-size: 15px; color: var(--text-tertiary); text-transform: uppercase; margin-bottom: var(--space-1); }
.binsp-seg-row { font-family: var(--font-mono); font-size: 15px; padding: 1px 0; }
.binsp-seg-name { color: var(--signal-blue, #5aa9e6); font-weight: 600; }
.binsp-seg-meta { color: var(--text-secondary); margin-left: 6px; }
.binsp-seg-src { color: var(--text-tertiary); margin-left: 6px; }
.vllm-row { display: flex; align-items: center; gap: 8px; font-family: var(--font-mono); font-size: 15px; }
.vllm-op { color: var(--signal-green, #7ec8a2); font-size: 15px; }
.vllm-ops { color: var(--text-tertiary); font-size: 15px; }
.vllm-weights { margin-top: var(--space-2); display: flex; flex-direction: column; gap: 2px; }
.vllm-weight { font-family: var(--font-mono); font-size: 15px; display: flex; gap: 8px; }
.vllm-w-name { color: var(--amber); }
.vllm-w-shape { color: var(--text-secondary); }
.vllm-w-loader { color: var(--text-tertiary); }
.binsp-fnote { color: var(--text-tertiary); font-size: 15px; font-style: italic; margin-top: var(--space-2); }
.binsp-port-role { font-size: 15px; color: var(--text-tertiary); margin-left: 2px; }
.binsp-port-desc { font-size: 15px; color: var(--text-tertiary); margin-left: 4px; font-style: italic; }
.binsp-port-opt { font-size: 15px; color: var(--amber); margin-left: 2px; }
.binsp-ports-desc { font-size: 15px; color: var(--text-tertiary); margin-top: var(--space-1); }
</style>