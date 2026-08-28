<script setup lang="ts">
/**
 * YAMLImportModal.vue —— YAML 导入弹窗
 * 粘贴 YAML → 导入 → 展示结果（errors/warnings）。
 */
import { ref, watch } from 'vue'

const props = defineProps<{
  open: boolean
  yamlText: string
  importing: boolean
  result: any
}>()
const emit = defineEmits<{
  'update:yamlText': [v: string]
  close: []
  doImport: []
}>()

const fileInput = ref<HTMLInputElement | null>(null)
const fileError = ref('')

async function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  fileError.value = ''
  if (!/\.(yaml|yml)$/i.test(file.name)) {
    fileError.value = '请选择 .yaml 或 .yml 文件'
    return
  }
  const text = await file.text()
  emit('update:yamlText', text)
}

watch(() => props.open, (v) => {
  if (v) emit('update:yamlText', '')
})
</script>

<template>
  <div v-if="open" class="modal-backdrop" @click="emit('close')">
    <div class="modal yaml-modal" @click.stop>
      <div class="modal-header">
        <h3>导入 YAML（唯一数据源）</h3>
        <button class="modal-close" @click="emit('close')">✕</button>
      </div>
      <div class="modal-body form-stack">
        <div class="yaml-file-row">
          <input ref="fileInput" type="file" accept=".yaml,.yml" class="hidden-input"
            @change="onFileChange" />
          <button class="btn btn-primary btn-sm" @click="fileInput?.click()">从文件导入…</button>
        </div>
        <div v-if="fileError" class="yaml-file-error">{{ fileError }}</div>
        <textarea class="textarea textarea-mono w-100 yaml-textarea"
          :value="yamlText" @input="emit('update:yamlText', ($event.target as HTMLTextAreaElement).value)"
          placeholder="# 粘贴算子/组装 YAML 内容…"></textarea>

        <div v-if="result" class="yaml-result">
          <div class="yaml-result-summary" :class="result.errors && result.errors.length ? 'has-err' : 'ok'">
            导入：算子 {{ result.imported_blocks || 0 }} 个，模型 {{ result.imported_assemblies || 0 }} 个，跳过 {{ result.skipped || 0 }} 个
          </div>
          <div v-if="result.errors && result.errors.length" class="yaml-issues is-err">
            <div v-for="(e, i) in result.errors" :key="i" class="yaml-issue">
              <span class="yaml-issue-path">{{ e.path }}</span> {{ e.message }}
            </div>
          </div>
          <div v-if="result.warnings && result.warnings.length" class="yaml-issues is-warn">
            <div v-for="(w, i) in result.warnings" :key="i" class="yaml-issue">
              <span class="yaml-issue-path">{{ w.path }}</span> {{ w.message }}
            </div>
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn" @click="emit('close')">关闭</button>
        <button class="btn btn-primary" @click="emit('doImport')" :disabled="importing || !yamlText.trim()">
          {{ importing ? '导入中…' : '导入' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.yaml-modal { max-width: 720px; width: 94%; }
.hidden-input { display: none; }
.yaml-file-row { display: flex; align-items: center; }
.yaml-file-error { color: var(--color-danger, #f4796b); font-size: 15px; margin-bottom: 6px; }
.yaml-textarea { height: 260px; font-size: 15px; }
.yaml-result { border-top: 1px solid var(--border-faint); padding-top: 10px; font-family: var(--font-mono); font-size: 15px; }
.yaml-result-summary.ok { color: var(--signal-green, #7ec8a2); }
.yaml-result-summary.has-err { color: var(--color-danger, #f4796b); }
.yaml-issues { margin-top: 8px; max-height: 200px; overflow: auto; display: flex; flex-direction: column; gap: 4px; }
.yaml-issue { font-size: 15px; }
.yaml-issues.is-err .yaml-issue { color: var(--color-danger, #f4796b); }
.yaml-issues.is-warn .yaml-issue { color: var(--amber); }
.yaml-issue-path { background: var(--bg-elev-3); padding: 0 4px; border-radius: 3px; }
</style>