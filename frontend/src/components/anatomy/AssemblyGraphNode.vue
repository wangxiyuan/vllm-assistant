<script setup lang="ts">
/**
 * AssemblyGraphNode.vue —— 图节点（递归渲染容器/子节点）
 *
 * node 带 children/edges 则为容器，渲染内部子节点；子节点若又带 children
 * 则递归。用于图视图的任意深度展开。
 */
import { ref } from 'vue'
import type { AnatomyBlock } from '@/utils/types'

interface GChild {
  id: string
  blockName?: string
  kind?: string
  label: string
  loopCount?: string
  condition?: string
  role?: string
  isSink?: boolean
  isSource?: boolean
  children?: GChild[]   // 子节点也是复合时继续展开
  edges?: any[]
}

const props = defineProps<{
  node: GChild
  blocks: AnatomyBlock[]
}>()

const expanded = ref<Set<string>>(new Set())
function toggle(id: string) {
  const s = new Set(expanded.value)
  if (s.has(id)) s.delete(id); else s.add(id)
  expanded.value = s
}
const isOpen = (id: string) => expanded.value.has(id)
</script>

<template>
  <!-- 容器节点：复合/组装，内部展开 -->
  <div v-if="node.children && node.children.length" class="agn-ctn">
    <div class="agn-ctn-head" @click="toggle(node.id)">
      <span class="agn-chev" :class="{ closed: !isOpen(node.id) }">▾</span>
      <span class="agn-kind" :class="node.kind">{{ node.kind }}</span>
      <span class="agn-name">{{ node.blockName }}</span>
      <span v-if="node.label && node.label !== node.blockName" class="agn-as">as {{ node.label }}</span>
      <span v-if="node.loopCount" class="agn-loop">×{{ node.loopCount }}</span>
      <span v-if="node.condition" class="agn-cond">{{ node.condition }}</span>
    </div>
    <div v-if="isOpen(node.id)" class="agn-ctn-body">
      <div class="agn-child-flow">
        <template v-for="(c, ci) in node.children" :key="c.id">
          <AssemblyGraphNode :node="c" :blocks="blocks" />
          <span v-if="ci < (node.children?.length || 0) - 1" class="agn-arrow">→</span>
        </template>
      </div>
      <div v-if="node.edges && node.edges.length" class="agn-edges">
        <div v-for="(e,i) in node.edges.slice(0,40)" :key="i" class="agn-edge">
          <span class="agn-e-from">{{ e.from?.id }}{{ e.from?.port ? '.' + e.from.port : '' }}{{ e.from_segment ? '[' + e.from_segment + ']' : '' }}</span>
          <span class="agn-e-arrow">→</span>
          <span class="agn-e-to">{{ e.to?.id }}{{ e.to?.port ? '.' + e.to.port : '' }}</span>
          <span v-if="e.condition" class="agn-e-cond">{{ e.condition }}</span>
          <span v-if="e.note" class="agn-e-note">{{ e.note }}</span>
        </div>
      </div>
    </div>
  </div>

  <!-- 原子节点 -->
  <div v-else class="agn-node" :class="{ sink: node.isSink, source: node.isSource }">
    <span class="agn-kind" :class="node.kind">{{ node.kind }}</span>
    <span class="agn-name">{{ node.blockName || node.id }}</span>
    <span v-if="node.loopCount" class="agn-loop">×{{ node.loopCount }}</span>
    <span v-if="node.role" class="agn-role">{{ node.role }}</span>
    <div v-if="node.condition" class="agn-cond inline">{{ node.condition }}</div>
  </div>
</template>

<script lang="ts">
import { defineComponent } from 'vue'
export default defineComponent({
  name: 'AssemblyGraphNode',
})
</script>

<style scoped>
.agn-ctn { min-width: 160px; background: var(--bg-elev-2); border: 2px dashed var(--amber-dim); border-radius: var(--radius-md); padding: 6px; align-self: flex-start; }
.agn-ctn-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; cursor: pointer; padding: 2px 4px; }
.agn-chev { transition: transform var(--t-fast); font-size: 15px; color: var(--text-tertiary); }
.agn-chev.closed { transform: rotate(-90deg); }
.agn-ctn-body { border-top: 1px dashed var(--border-faint); padding-top: 6px; }
.agn-child-flow { display: flex; flex-wrap: wrap; gap: 8px; align-items: flex-start; }
.agn-node { min-width: 120px; background: var(--bg-elev-1); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 5px 8px; display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.agn-node.source { border-color: var(--signal-blue, #5aa9e6); }
.agn-node.sink { border-color: var(--signal-green, #7ec8a2); }
.agn-kind { font-size: 15px; text-transform: uppercase; letter-spacing: 0.04em; background: var(--bg-elev-4); color: var(--text-tertiary); padding: 1px 5px; border-radius: 3px; font-family: var(--font-mono); }
.agn-kind.atomic { color: var(--amber); }
.agn-kind.composite { color: var(--signal-blue, #5aa9e6); }
.agn-kind.assembly { color: var(--signal-green, #7ec8a2); }
.agn-name { font-family: var(--font-mono); font-size: 15px; font-weight: 600; color: var(--text-primary); }
.agn-as { font-size: 15px; color: var(--text-secondary); }
.agn-loop { background: var(--amber); color: var(--text-on-accent, #0b0b0c); font-family: var(--font-mono); font-size: 15px; font-weight: 700; padding: 0 6px; border-radius: 9px; }
.agn-cond { font-size: 15px; color: var(--amber); }
.agn-cond.inline { width: 100%; }
.agn-role { font-size: 15px; color: var(--text-tertiary); }
.agn-arrow { color: var(--text-tertiary); font-size: 15px; align-self: center; }
.agn-edges { margin-top: 6px; border-top: 1px dashed var(--border-faint); padding-top: 5px; font-family: var(--font-mono); font-size: 15px; display: flex; flex-direction: column; gap: 2px; }
.agn-edge { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; white-space: nowrap; }
.agn-e-from { color: var(--signal-blue, #5aa9e6); }
.agn-e-to { color: var(--signal-green, #7ec8a2); }
.agn-e-arrow { color: var(--text-tertiary); }
.agn-e-cond { color: var(--amber); }
.agn-e-note { color: var(--text-tertiary); }
</style>