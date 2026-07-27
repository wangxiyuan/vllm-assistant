<script setup lang="ts">
/**
 * ParamsSummary.vue - Recursive params_summary renderer.
 *
 * Scalar values render as stat cards; nested objects (e.g. text_config,
 * vision_config) render as collapsible sections that recurse into the
 * same component.
 */
import { ref, computed } from 'vue'

const props = defineProps<{
  data: Record<string, any>
  level?: number
  title?: string
  defaultOpen?: boolean
}>()

const level = computed(() => props.level ?? 0)
const open = ref(props.defaultOpen ?? level.value === 0)

const scalars = computed(() => {
  const out: Array<{ key: string; val: any }> = []
  for (const [k, v] of Object.entries(props.data)) {
    if (v !== null && typeof v === 'object' && !Array.isArray(v)) continue
    out.push({ key: k, val: v })
  }
  return out
})

const nested = computed(() => {
  const out: Array<{ key: string; val: Record<string, any> }> = []
  for (const [k, v] of Object.entries(props.data)) {
    if (v !== null && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length > 0) {
      out.push({ key: k, val: v as Record<string, any> })
    }
  }
  return out
})

function formatVal(val: any): string {
  if (val === null || val === undefined) return '—'
  if (Array.isArray(val)) return val.join(', ')
  if (typeof val === 'boolean') return val ? 'true' : 'false'
  return String(val)
}

function toggle() {
  open.value = !open.value
}
</script>

<template>
  <div class="params-summary" :class="`params-summary-l${level}`">
    <!-- Collapsible header (nested levels only) -->
    <button v-if="level > 0" class="params-section-toggle" @click="toggle">
      <span class="params-toggle-arrow" :class="{ 'is-open': open }">▶</span>
      <span class="params-section-title">{{ title }}</span>
      <span class="params-section-count">{{ Object.keys(data).length }} 项</span>
    </button>

    <div v-show="level === 0 || open">
      <!-- Scalar values as stat cards -->
      <div v-if="scalars.length > 0" class="params-scalar-grid">
        <div v-for="item in scalars" :key="item.key" class="params-scalar-card">
          <div class="params-scalar-label">{{ item.key }}</div>
          <div class="params-scalar-value">{{ formatVal(item.val) }}</div>
        </div>
      </div>

      <!-- Nested objects as recursive sections -->
      <div v-for="item in nested" :key="item.key" class="params-nested">
        <ParamsSummary :data="item.val" :level="level + 1" :title="item.key" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.params-summary {
  margin-bottom: var(--space-4);
}
.params-summary-l0 > .params-scalar-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.params-scalar-card {
  background: var(--bg-elev-1);
  border: 1px solid var(--border-faint);
  border-radius: var(--radius);
  padding: var(--space-3) var(--space-4);
  position: relative;
  overflow: hidden;
}
.params-scalar-card::before {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--signal-blue);
  opacity: 0.6;
}
.params-scalar-label {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-tertiary);
  margin-bottom: var(--space-2);
  font-weight: 600;
}
.params-scalar-value {
  font-family: var(--font-mono);
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--amber-bright);
  line-height: 1.2;
  word-break: break-all;
}

/* Nested sections */
.params-nested {
  margin-top: var(--space-3);
}
.params-section-toggle {
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
.params-section-toggle:hover {
  background: var(--bg-elev-3);
  border-color: var(--border);
  color: var(--text-primary);
}
.params-toggle-arrow {
  display: inline-block;
  font-size: 9px;
  color: var(--amber);
  transition: transform var(--t-base) var(--ease-out);
}
.params-toggle-arrow.is-open {
  transform: rotate(90deg);
}
.params-section-title {
  flex: 1;
  color: var(--text-primary);
}
.params-section-count {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  background: var(--bg-elev-3);
  padding: 1px 7px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border-faint);
  font-weight: 500;
}

/* Nested level: indent + left border accent */
.params-summary-l1 .params-scalar-grid,
.params-summary-l2 .params-scalar-grid,
.params-summary-l3 .params-scalar-grid {
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: var(--space-2);
  margin-top: var(--space-3);
  margin-bottom: var(--space-3);
  padding-left: var(--space-3);
  border-left: 2px solid var(--border-faint);
}
.params-summary-l1 .params-scalar-card {
  padding: var(--space-2) var(--space-3);
}
.params-summary-l1 .params-scalar-value {
  font-size: var(--text-sm);
  color: var(--text-primary);
}
</style>
