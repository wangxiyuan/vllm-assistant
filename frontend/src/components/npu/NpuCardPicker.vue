<script setup lang="ts">
/**
 * NPU 卡号多选选择器
 * 按机器渲染卡号 chips：已占用（运行中服务/常驻任务声明）的卡禁选并标注占用者；
 * 全不选 = 使用全部卡。空选择通过 v-null 约定表示全部卡。
 */
import { ref, watch } from 'vue'
import { useNpuStore } from '@/stores/npu'

const props = defineProps<{
  machineId: number | null
  modelValue: number[] | null // null = 全部卡
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: number[] | null): void }>()

const npu = useNpuStore()
const total = ref(0)
const occupied = ref<Record<string, string>>({})
const loading = ref(false)

async function load() {
  if (!props.machineId) { total.value = 0; occupied.value = {}; return }
  loading.value = true
  try {
    const r = await npu.fetchMachineNpus(props.machineId)
    total.value = r.total || 0
    occupied.value = r.occupied || {}
    // 选择中含已占用卡时自动剔除
    const sel = (props.modelValue || []).filter(i => !occupied.value[String(i)])
    if (sel.length !== (props.modelValue || []).length) emit('update:modelValue', sel)
  } catch { total.value = 0 } finally { loading.value = false }
}

watch(() => props.machineId, load, { immediate: true })

function toggle(i: number) {
  if (occupied.value[String(i)]) return
  const sel = [...(props.modelValue || [])]
  const idx = sel.indexOf(i)
  if (idx >= 0) sel.splice(idx, 1)
  else sel.push(i)
  sel.sort((a, b) => a - b)
  // 全选 = 等价于全部卡 → 返回 null
  emit('update:modelValue', (total.value && sel.length === total.value) ? null : sel)
}

function isOccupied(i: number) { return !!occupied.value[String(i)] }
function isSelected(i: number) {
  // null = 全部卡 → 视为全选
  return props.modelValue === null || (props.modelValue || []).includes(i)
}
function isAll() { return props.modelValue === null || (total.value > 0 && (props.modelValue || []).length === total.value) }
</script>

<template>
  <div class="card-picker">
    <div v-if="!machineId" class="cp-hint">先选择机器</div>
    <template v-else>
      <button type="button" class="cp-chip" :class="{ on: isAll() }" @click="emit('update:modelValue', null)">
        全部卡{{ total ? `（${total}）` : '' }}
      </button>
      <button
        v-for="i in total"
        :key="i"
        type="button"
        class="cp-chip"
        :class="{ on: isSelected(i - 1) && !isOccupied(i - 1), busy: isOccupied(i - 1) }"
        :disabled="isOccupied(i - 1)"
        :title="isOccupied(i - 1) ? `已被 ${occupied[String(i - 1)]} 占用` : `NPU ${i - 1}`"
        @click="toggle(i - 1)"
      >{{ i - 1 }}</button>
      <span v-if="loading" class="cp-hint">加载中…</span>
    </template>
  </div>
</template>

<style scoped>
.card-picker { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }
.cp-chip {
  min-width: 30px; height: 24px; padding: 0 8px;
  border: 1px solid var(--border-faint); border-radius: 5px;
  background: var(--bg-elev-2); color: var(--text-secondary);
  font-size: var(--text-xs); cursor: pointer; transition: all 0.15s;
}
.cp-chip:hover:not(:disabled) { border-color: var(--amber); }
.cp-chip.on { background: var(--amber); border-color: var(--amber); color: var(--text-on-accent); font-weight: 600; }
.cp-chip.busy {
  background: var(--bg-elev-1); color: var(--text-disabled);
  border-style: dashed; cursor: not-allowed; text-decoration: line-through;
}
.cp-hint { font-size: var(--text-xs); color: var(--text-tertiary); }
</style>
