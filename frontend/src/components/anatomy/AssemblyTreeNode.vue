<script setup lang="ts">
/**
 * AssemblyTreeNode.vue —— 递归渲染一个组装树节点及其子树
 * 通过自身 name 'AssemblyTreeNode' 实现自递归。
 */
import { ref } from 'vue'
import CondBadge from '@/components/anatomy/CondBadge.vue'

interface RNode {
  key: string
  label: string
  blockName?: string
  kind?: string
  state?: string
  condition?: string
  conditionTruthy?: boolean | null
  role?: string
  depth: number
  loopCount?: string
  children: RNode[]
}

const props = defineProps<{ node: RNode }>()
const collapsed = ref<Set<string>>(new Set())
function toggle(key: string) {
  const s = new Set(collapsed.value)
  if (s.has(key)) s.delete(key); else s.add(key)
  collapsed.value = s
}
const isCollapsed = (k: string) => collapsed.value.has(k)
</script>

<template>
  <div class="atn-node">
    <div class="atn-row" @click="node.children.length && toggle(node.key)">
      <span class="atn-chev" v-if="node.children.length" :class="{ collapsed: isCollapsed(node.key) }">▾</span>
      <span class="atn-dot" v-else></span>
      <span class="atn-kind" :class="node.kind" v-if="node.blockName">{{ node.kind }}</span>
      <span class="atn-label">{{ node.label }}</span>
      <span class="atn-block" v-if="node.blockName && node.blockName !== node.label">{{ node.blockName }}</span>
      <span v-if="node.loopCount" class="atn-state">×{{ node.loopCount }}</span>
      <CondBadge v-if="node.condition" class="atn-cond" :expr="node.condition" :truthy="node.conditionTruthy" />
      <span v-if="node.role" class="atn-role">{{ node.role }}</span>
    </div>
    <div v-if="node.children.length && !isCollapsed(node.key)" class="atn-children">
      <AssemblyTreeNode v-for="child in node.children" :key="child.key" :node="child" />
    </div>
  </div>
</template>

<script lang="ts">
import { defineComponent } from 'vue'
export default defineComponent({
  name: 'AssemblyTreeNode',
})
</script>

<style scoped>
.atn-node { }
.atn-row { display: flex; align-items: center; gap: 6px; padding: 3px 6px; border-radius: var(--radius-xs); cursor: default; }
.atn-row:hover { background: var(--bg-elev-3); }
.atn-chev { font-size: 15px; color: var(--text-tertiary); transition: transform var(--t-fast); cursor: pointer; width: 12px; }
.atn-chev.collapsed { transform: rotate(-90deg); }
.atn-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-tertiary); opacity: 0.5; flex: none; }
.atn-kind { font-size: 15px; text-transform: uppercase; letter-spacing: 0.04em; padding: 1px 5px; border-radius: 3px; background: var(--bg-elev-3); color: var(--text-tertiary); font-family: var(--font-mono); }
.atn-kind.atomic { color: var(--amber); }
.atn-kind.composite { color: var(--signal-blue, #5aa9e6); }
.atn-kind.assembly { color: var(--signal-green, #7ec8a2); }
.atn-label { font-family: var(--font-mono); font-size: 15px; font-weight: 600; color: var(--text-primary); }
.atn-block { font-family: var(--font-mono); font-size: 15px; color: var(--text-tertiary); margin-left: auto; }
.atn-cond.cb { font-size: 15px; margin-left: 6px; flex: none; max-width: 260px; vertical-align: middle; }
.atn-state { background: var(--amber); color: var(--text-on-accent, #0b0b0c); font-family: var(--font-mono); font-size: 15px; font-weight: 700; padding: 0 6px; border-radius: 9px; }
.atn-role { font-size: 15px; color: var(--text-tertiary); margin-left: 6px; }
.atn-children { border-left: 1px dashed var(--border-faint); margin-left: 12px; padding-left: 6px; }
</style>