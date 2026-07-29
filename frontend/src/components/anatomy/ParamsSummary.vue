<script setup lang="ts">
import { ref, computed } from 'vue'
import Icon from '@/components/common/Icon.vue'

const props = defineProps<{
  data: Record<string, any>
  level?: number
  title?: string
  defaultOpen?: boolean
}>()

const level = computed(() => props.level ?? 0)
const open = ref(props.defaultOpen ?? level.value === 0)

const allOpen = ref(true)

const safeData = computed(() => {
  if (!props.data || typeof props.data !== 'object') return {}
  return props.data
})

const scalars = computed(() => {
  const out: Array<{ key: string; val: any }> = []
  for (const [k, v] of Object.entries(safeData.value)) {
    if (v !== null && typeof v === 'object' && !Array.isArray(v)) continue
    out.push({ key: k, val: v })
  }
  return out
})

const nested = computed(() => {
  const out: Array<{ key: string; val: Record<string, any> }> = []
  for (const [k, v] of Object.entries(safeData.value)) {
    if (v !== null && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length > 0) {
      out.push({ key: k, val: v as Record<string, any> })
    }
  }
  return out
})

function formatVal(val: any): string {
  if (val === null || val === undefined) return '-'
  if (Array.isArray(val)) return val.join(', ')
  if (typeof val === 'boolean') return val ? 'true' : 'false'
  return String(val)
}

function toggle() {
  open.value = !open.value
}

function toggleAll() {
  allOpen.value = !allOpen.value
  open.value = allOpen.value
}
</script>

<template>
  <div class="params-summary" :class="`params-summary-l${level}`">
    <!-- Top-level controls -->
    <div v-if="level === 0 && (scalars.length > 0 || nested.length > 0)" class="ps-controls">
      <button class="ps-toggle-all" @click="toggleAll">
        {{ allOpen ? '折叠全部' : '展开全部' }}
      </button>
    </div>

    <!-- Collapsible header (nested levels only) -->
    <button v-if="level > 0" class="ps-section-toggle" @click="toggle">
      <span class="ps-toggle-arrow" :class="{ 'is-open': open }"><Icon name="chevronRight" :size="9" /></span>
      <span class="ps-section-title">{{ title }}</span>
      <span class="ps-section-count">{{ Object.keys(safeData).length }} 项</span>
    </button>

    <div v-show="level === 0 || open">
      <!-- Scalar values as compact key-value rows -->
      <div v-if="scalars.length > 0" class="ps-scalar-list">
        <div v-for="(item, i) in scalars" :key="item.key" class="ps-scalar-row" :class="{ alt: i % 2 === 1 }">
          <span class="ps-scalar-key">{{ item.key }}</span>
          <span class="ps-scalar-sep">:</span>
          <span class="ps-scalar-val">{{ formatVal(item.val) }}</span>
        </div>
      </div>

      <!-- Nested objects as recursive sections -->
      <div v-for="item in nested" :key="item.key" class="ps-nested">
        <ParamsSummary :data="item.val" :level="level + 1" :title="item.key" :default-open="false" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.params-summary {
  margin-bottom: var(--space-3);
}

.ps-controls {
  margin-bottom: var(--space-2);
}
.ps-toggle-all {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--amber);
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 2px 0;
  transition: color var(--t-fast);
}
.ps-toggle-all:hover {
  color: var(--amber-bright);
}

/* Compact scalar list */
.ps-scalar-list {
  border: 1px solid var(--border-faint);
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: var(--bg-elev-1);
}
.ps-scalar-row {
  display: flex;
  align-items: baseline;
  gap: var(--space-1);
  padding: 3px var(--space-3);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  line-height: 1.5;
  transition: background var(--t-fast);
}
.ps-scalar-row.alt {
  background: var(--bg-elev-2);
}
.ps-scalar-row:hover {
  background: var(--bg-elev-3);
}
.ps-scalar-key {
  color: var(--text-tertiary);
  font-weight: 600;
  flex-shrink: 0;
}
.ps-scalar-sep {
  color: var(--text-disabled);
}
.ps-scalar-val {
  color: var(--amber-bright);
  word-break: break-all;
}

/* Nested sections */
.ps-nested {
  margin-top: var(--space-2);
}
.ps-section-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  background: var(--bg-elev-2);
  border: 1px solid var(--border-faint);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  font-weight: 600;
  cursor: pointer;
  transition: all var(--t-base);
  text-align: left;
}
.ps-section-toggle:hover {
  background: var(--bg-elev-3);
  border-color: var(--border);
  color: var(--text-primary);
}
.ps-toggle-arrow {
  display: inline-block;
  font-size: 9px;
  color: var(--amber);
  transition: transform var(--t-base) var(--ease-out);
}
.ps-toggle-arrow.is-open {
  transform: rotate(90deg);
}
.ps-section-title {
  flex: 1;
  color: var(--text-primary);
}
.ps-section-count {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  background: var(--bg-elev-3);
  padding: 1px 7px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border-faint);
  font-weight: 500;
}

/* Nested level: indent + left border accent */
.params-summary-l1 .ps-scalar-list,
.params-summary-l2 .ps-scalar-list,
.params-summary-l3 .ps-scalar-list {
  margin-top: var(--space-2);
  margin-left: var(--space-3);
  border-left: 2px solid var(--border-faint);
}
.params-summary-l1 .ps-scalar-row {
  font-size: var(--text-xs);
}
.params-summary-l1 .ps-scalar-val {
  color: var(--text-primary);
}
</style>
