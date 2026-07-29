<script setup lang="ts">
import { ref, computed, watch } from 'vue'

const props = defineProps<{
  modelValue: string
}>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const mode = ref<'form' | 'json'>('form')
const jsonText = ref(props.modelValue || '')
const jsonError = ref('')

const parsedData = computed<Record<string, any>>(() => {
  try {
    const val = JSON.parse(props.modelValue || '{}')
    return (val && typeof val === 'object' && !Array.isArray(val)) ? val : {}
  } catch {
    return {}
  }
})

watch(() => props.modelValue, (v) => {
  jsonText.value = v || ''
  if (mode.value === 'json') {
    try {
      JSON.parse(v || '{}')
      jsonError.value = ''
    } catch (e: any) {
      jsonError.value = e.message
    }
  }
})

function syncFromJson() {
  try {
    const val = JSON.parse(jsonText.value || '{}')
    jsonError.value = ''
    emit('update:modelValue', JSON.stringify(val, null, 2))
  } catch (e: any) {
    jsonError.value = e.message
  }
}

function updateField(key: string, value: any) {
  const data = { ...parsedData.value }
  data[key] = value
  emit('update:modelValue', JSON.stringify(data, null, 2))
}

function addField() {
  const data = { ...parsedData.value }
  let n = 1
  while (data[`field_${n}`] !== undefined) n++
  data[`field_${n}`] = ''
  emit('update:modelValue', JSON.stringify(data, null, 2))
}

function removeField(key: string) {
  const data = { ...parsedData.value }
  delete data[key]
  emit('update:modelValue', JSON.stringify(data, null, 2))
}

function renameField(oldKey: string, newKey: string) {
  newKey = newKey.trim()
  if (!newKey || newKey === oldKey) return
  if (parsedData.value[newKey] !== undefined) return
  const data: Record<string, any> = {}
  for (const [k, v] of Object.entries(parsedData.value)) {
    data[k === oldKey ? newKey : k] = v
  }
  emit('update:modelValue', JSON.stringify(data, null, 2))
}

function inferType(val: any): 'string' | 'number' | 'boolean' {
  if (typeof val === 'boolean') return 'boolean'
  if (typeof val === 'number') return 'number'
  return 'string'
}

function coerceValue(raw: string, type: 'string' | 'number' | 'boolean'): any {
  if (type === 'number') {
    const n = Number(raw)
    return isNaN(n) ? raw : n
  }
  if (type === 'boolean') {
    return raw === 'true'
  }
  return raw
}

function formatVal(val: any): string {
  if (val === null || val === undefined) return ''
  return String(val)
}

const scalarEntries = computed(() => {
  return Object.entries(parsedData.value).filter(
    ([, v]) => v === null || typeof v !== 'object' || Array.isArray(v)
  )
})
</script>

<template>
  <div class="pse-wrapper">
    <div class="pse-mode-toggle">
      <button class="pse-mode-btn" :class="{ active: mode === 'form' }" @click="mode = 'form'">表单模式</button>
      <button class="pse-mode-btn" :class="{ active: mode === 'json' }" @click="mode = 'json'">JSON 模式</button>
    </div>

    <!-- Form mode -->
    <div v-if="mode === 'form'" class="pse-form">
      <div v-if="scalarEntries.length === 0" class="pse-empty">
        暂无参数，点击「+ 添加字段」开始
      </div>
      <div v-for="[key, val] in scalarEntries" :key="key" class="pse-row">
        <input class="input input-sm pse-key" :value="key"
               @change="renameField(key, ($event.target as HTMLInputElement).value)"
               placeholder="字段名">
        <select class="select select-sm pse-type" :value="inferType(val)"
                @change="updateField(key, coerceValue(formatVal(val), ($event.target as HTMLSelectElement).value as any))">
          <option value="string">文本</option>
          <option value="number">数字</option>
          <option value="boolean">布尔</option>
        </select>
        <input v-if="inferType(val) !== 'boolean'" class="input input-sm pse-value"
               :type="inferType(val) === 'number' ? 'number' : 'text'"
               :value="formatVal(val)"
               @input="updateField(key, coerceValue(($event.target as HTMLInputElement).value, inferType(val)))"
               placeholder="值">
        <select v-else class="select select-sm pse-value"
                :value="String(val)"
                @change="updateField(key, ($event.target as HTMLSelectElement).value === 'true')">
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
        <button class="card-action-btn is-danger pse-remove" @click="removeField(key)" title="删除">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
      <button class="btn btn-sm pse-add-btn" @click="addField()">+ 添加字段</button>
      <div class="pse-hint">提示：仅标量字段支持表单编辑，嵌套对象请切换 JSON 模式</div>
    </div>

    <!-- JSON mode -->
    <div v-if="mode === 'json'" class="pse-json">
      <textarea class="textarea textarea-mono pse-json-area" v-model="jsonText"
                @input="syncFromJson()" rows="6"
                placeholder='{"total_params": "7B", "hidden_size": 4096}'></textarea>
      <div v-if="jsonError" class="form-error">JSON 格式错误: {{ jsonError }}</div>
    </div>
  </div>
</template>

<style scoped>
.pse-wrapper {
  border: 1px solid var(--border-faint);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.pse-mode-toggle {
  display: flex;
  gap: 0;
  border-bottom: 1px solid var(--border-faint);
  background: var(--bg-elev-2);
}
.pse-mode-btn {
  padding: 4px 12px;
  font-size: var(--text-xs);
  font-family: var(--font-mono);
  color: var(--text-tertiary);
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all var(--t-fast);
  font-weight: 600;
}
.pse-mode-btn:hover {
  color: var(--text-primary);
  background: var(--bg-elev-3);
}
.pse-mode-btn.active {
  color: var(--amber);
  border-bottom: 2px solid var(--amber);
}
.pse-form {
  padding: var(--space-3);
}
.pse-empty {
  text-align: center;
  color: var(--text-tertiary);
  font-size: var(--text-sm);
  padding: var(--space-4);
}
.pse-row {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  margin-bottom: var(--space-2);
}
.pse-key {
  flex: 1;
  min-width: 0;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
}
.pse-type {
  flex: 0 0 70px;
  font-size: var(--text-2xs);
}
.pse-value {
  flex: 1;
  min-width: 0;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
}
.pse-remove {
  flex: 0 0 auto;
}
.pse-add-btn {
  margin-top: var(--space-1);
}
.pse-hint {
  margin-top: var(--space-2);
  font-size: var(--text-2xs);
  color: var(--text-tertiary);
}
.pse-json-area {
  width: 100%;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  border: none;
  border-radius: 0;
}
</style>
