<script setup lang="ts">
/**
 * MindRoot.vue —— 思维导图根：顶层节点垂直堆叠，各自往右展开
 */
import { defineProps } from 'vue'
import MindNode from '@/components/anatomy/MindNode.vue'

interface MNode {
  id: string
  label: string
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

const props = defineProps<{
  nodes: MNode[]
  expandAll?: boolean
}>()
</script>

<template>
  <div class="mr">
    <template v-for="(n, i) in nodes" :key="n.id">
      <div class="mr-flow">
        <MindNode :node="n" :expandAll="expandAll" />
      </div>
      <!-- 下箭头：居中于该层的根节点列 -->
      <div v-if="i < nodes.length - 1" class="mr-arrow-wrap">
        <span class="mr-arrow-line"></span>
        <svg class="mr-arrow-head" width="12" height="10" viewBox="0 0 12 10" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="1 2 6 8 11 2"/>
        </svg>
      </div>
    </template>
  </div>
</template>

<style scoped>
.mr { display: flex; flex-direction: column; padding: 4px; }
.mr-flow { display: flex; }
/* 下箭头：居中于该层根节点（左列固定 180px）下方 */
.mr-arrow-wrap { display: flex; flex-direction: column; align-items: center; width: 11.25em; padding: 0.18em 0; }
.mr-arrow-line { width: 2px; height: 1em; background: var(--border-strong, var(--border)); opacity: 0.7; }
.mr-arrow-head { color: var(--text-tertiary); margin-top: -3px; }
</style>