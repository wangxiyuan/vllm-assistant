<script setup lang="ts">
/**
 * MindNode.vue —— 思维导图式递归节点
 * 节点框在左；若含子节点，则往右连接一列子节点（子节点自身可再右扩）。
 *
 * 复合/组装节点默认折叠，点击标题栏展开/收起；叶子节点直接展示。
 * 连接线：节点右缘 → 子列中心（垂直居中）。
 */
import { ref, computed, watch } from 'vue'
import CondBadge from '@/components/anatomy/CondBadge.vue'

interface MNode {
  id: string
  label: string          // 显示名（as/blockName）
  blockName?: string
  kind?: string
  loopCount?: string
  condition?: string
  conditionTruthy?: boolean | null
  role?: string
  isSource?: boolean
  isSink?: boolean
  hasChildren?: boolean
  children?: MNode[]
}

const props = defineProps<{ node: MNode; expandAll?: boolean }>()

// 默认折叠，但 expandAll=true 时强制展开
const open = ref(false)
watch(() => props.expandAll, (v) => { open.value = !!v }, { immediate: true })
const isContainer = computed(() => !!(props.node.children && props.node.children.length))
function toggle() {
  if (isContainer.value) open.value = !open.value
}
</script>

<template>
  <div class="mn-row" :class="{ open: open && isContainer }">
    <!-- 节点框 -->
    <div class="mn-node"
      :class="{ source: node.isSource, sink: node.isSink, ctn: isContainer, leaf: !isContainer, open: open }"
      :title="isContainer ? (open ? '点击收起' : '点击展开') : ''"
      @click="toggle">
      <!-- 展开/折叠指示 -->
      <span v-if="isContainer" class="mn-toggle">
        <svg :class="{ closed: !open }" width="inherit" height="inherit" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="2"><polyline points="2,3 5,7 8,3"/></svg>
      </span>
      <span class="mn-kind" :class="node.kind" v-if="node.blockName">{{ node.kind }}</span>
      <span class="mn-label">{{ node.label }}</span>
      <span class="mn-block" v-if="node.blockName && node.blockName !== node.label">{{ node.blockName }}</span>
      <span v-if="node.loopCount" class="mn-loop">×{{ node.loopCount }}</span>
      <CondBadge v-if="node.condition" class="mn-cond" :expr="node.condition" :truthy="node.conditionTruthy" />
    </div>

    <!-- 子节点列（往右），仅在展开时显示 -->
    <div v-if="isContainer && open" class="mn-sub">
      <template v-for="(c, i) in node.children" :key="c.id">
        <div class="mn-item">
          <MindNode :node="c" :expandAll="expandAll" />
          <span v-if="i < (node.children?.length || 0) - 1" class="mn-ylist"></span>
        </div>
      </template>
      <div v-if="!(node.children && node.children.length)" class="mn-empty">（空）</div>
    </div>
  </div>
</template>

<script lang="ts">
import { defineComponent } from 'vue'
export default defineComponent({ name: 'MindNode' })
</script>

<style scoped>
.mn-row { display: flex; align-items: center; gap: 1.25em; }
/* 节点框 */
.mn-node {
  min-width: 11.25em;
  max-width: 32em;
  background: var(--bg-elev-2); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: 0.375em 0.625em;
  display: flex; flex-direction: column; gap: 0.18em;
  position: relative;
  cursor: default;
  box-sizing: border-box;
  word-break: break-word; overflow-wrap: break-word;
}
.mn-node.ctn { cursor: pointer; border-color: var(--amber-dim); }
.mn-node.open { border-color: var(--amber); box-shadow: var(--amber-glow-soft); }
/* 横向连接线（容器节点右侧 → 子列纵向脊柱） */
.mn-node::after {
  content: ''; position: absolute; top: 50%; right: -1.25em; width: 1.25em;
  height: 2px; background: var(--border-bright); transform: translateY(-1px);
}
.mn-node.open::after { background: var(--amber); }
/* 叶子节点右侧无子列，不画悬空横线 */
.mn-node.leaf::after { display: none; }
.mn-node.source { border-color: var(--signal-blue, #5aa9e6); }
.mn-node.sink { border-color: var(--signal-green, #7ec8a2); }

/* 展开/收起三角 */
.mn-toggle { position: absolute; top: 0.3em; right: 0.3em; color: var(--amber); display: flex; align-items: center; justify-content: center; width: 1.4em; height: 1.4em; border-radius: 4px; cursor: pointer; }
.mn-toggle:hover { background: var(--amber-glow-soft); }
.mn-toggle svg { transition: transform var(--t-fast); display: block; width: 100%; height: 100%; }
.mn-toggle svg.closed { transform: rotate(-90deg); }

.mn-kind { font-size: 0.6em; text-transform: uppercase; letter-spacing: 0.04em; background: var(--bg-elev-4); color: var(--text-tertiary); padding: 0.06em 0.3em; border-radius: 3px; align-self: flex-start; font-family: var(--font-mono); }
.mn-kind.atomic { color: var(--amber); }
.mn-kind.composite { color: var(--signal-blue, #5aa9e6); }
.mn-kind.assembly { color: var(--signal-green, #7ec8a2); }
.mn-label { font-family: var(--font-mono); font-size: 0.82em; font-weight: 600; color: var(--text-primary); word-break: break-word; overflow-wrap: anywhere; }
.mn-block { font-family: var(--font-mono); font-size: 0.68em; color: var(--text-secondary); word-break: break-word; overflow-wrap: anywhere; }
.mn-loop { background: var(--amber); color: var(--text-on-accent, #0b0b0c); font-family: var(--font-mono); font-size: 0.66em; font-weight: 700; padding: 0 0.375em; border-radius: 9px; align-self: flex-start; }
/* 条件徽章：在节点内容下方独立一行，不遮挡 kind/label */
.mn-node .mn-cond.cb {
  position: static; margin-top: 0.1em; align-self: stretch;
  max-width: 100%; pointer-events: auto; justify-content: flex-start;
  white-space: normal;
}
.mn-node .mn-cond.cb .cb-expr {
  white-space: normal; overflow: visible; word-break: break-all;
}

/* 子列（右侧子树）：左侧一条连续竖直“脊柱”，
   每个子节点一条“折线”横向接入：短线从脊柱接到节点中部 */
.mn-sub {
  display: flex; flex-direction: column; gap: 1.5em;
  border-left: 2px solid var(--border-bright);
}
.mn-item { position: relative; margin-left: 1.125em; display: flex; flex-direction: column; }
/* 脊柱 → 子节点盒子 的横向接入短线（折线拐弯处） */
.mn-item::before {
  content: ''; position: absolute; left: -1.125em; top: 50%;
  width: 1.125em; height: 2px; background: var(--border-bright); transform: translateY(-1px);
}
.mn-empty { color: var(--text-tertiary); font-size: 0.69em; font-style: italic; padding: 4px 0; }
</style>