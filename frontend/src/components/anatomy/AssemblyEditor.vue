<script setup lang="ts">
/**
 * AssemblyEditor.vue —— 编辑模型（基础字段 + YAML 正文）
 * YAML 承载全部结构字段；保存走 apply-yaml。
 */
import { ref, onMounted } from 'vue'
import { useAnatomyStore } from '@/stores/anatomy'

const props = defineProps<{
  form: any
  blocks: any[]
}>()
const emit = defineEmits<{
  close: []
  saved: []
}>()

const store = useAnatomyStore()
const yamlText = ref('')
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    if (props.form?.id) {
      yamlText.value = await store.fetchAssemblyYaml(props.form.id)
    } else {
      yamlText.value = await store.fetchYamlTemplate('assembly')
      yamlText.value = applyBasics(yamlText.value, props.form)
    }
  } finally {
    loading.value = false
  }
}
function applyBasics(text: string, f: any): string {
  let t = text
  const set = (lineRe: RegExp, val: string) => {
    const m = t.match(lineRe)
    if (m) {
      const indent = m[0].match(/^\s*/)![0]
      t = t.replace(lineRe, `${indent}${val}`)
    } else {
      const nameM = t.match(/^(\s*)name:.*$/m)
      if (nameM) {
        const i = (nameM.index ?? 0) + nameM[0].length
        t = t.slice(0, i) + '\n' + nameM[1] + `${val}` + t.slice(i)
      }
    }
  }
  if (f.name != null) set(/^(\s*)name:.*$/m, `name: ${f.name}`)
  if (f.category != null) set(/^(\s*)category:.*$/m, `category: ${f.category}`)
  if (f.description) set(/^(\s*)description:.*$/m, `description: ${f.description}`)
  return t
}

onMounted(load)

async function commitSave() {
  if (!yamlText.value.trim()) { store.saveViaYaml(''); return }
  loading.value = true
  const ok = await store.saveViaYaml(yamlText.value)
  loading.value = false
  if (ok) emit('saved')
}
</script>

<template>
  <div class="modal-backdrop" @click="emit('close')">
    <div class="modal" @click.stop style="max-width:860px;width:95%;">
      <div class="modal-header">
        <h3>编辑模型</h3>
        <button class="modal-close" @click="emit('close')">✕</button>
      </div>
      <div class="modal-body form-stack">
        <div class="grid-2">
          <div class="field"><label class="form-label form-label-required">名称</label><input class="input w-100" v-model="form.name" placeholder="如 Glm5NextModel"></div>
          <div class="field"><label class="form-label">分类</label><input class="input w-100" v-model="form.category" placeholder="如 hybrid"></div>
        </div>
        <div class="field"><label class="form-label">描述</label><input class="input w-100" v-model="form.description"></div>

        <div class="field">
          <label class="form-label">YAML（唯一数据源，含 steps/edges/ports/config/公式等）</label>
          <textarea v-if="!loading" class="textarea textarea-mono w-100 yaml-area" v-model="yamlText" spellcheck="false"></textarea>
          <div v-else class="empty-state"><div class="empty-title">加载中…</div></div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn" @click="emit('close')">取消</button>
        <button class="btn btn-primary" @click="commitSave" :disabled="loading || !yamlText.trim()">保存</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.grid-2 { align-items: flex-start; }
.grid-2 .field { margin-top: 0; align-self: stretch; }
.grid-2 .field .form-label { min-height: 1.4em; }
.yaml-area { min-height: 58vh; font-size: 13px; line-height: 1.55; tab-size: 2; }
</style>