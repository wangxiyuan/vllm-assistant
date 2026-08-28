<script setup lang="ts">
/**
 * BlockEditor.vue —— 算子/层编辑（基础字段 + YAML 正文）
 *
 * 基础字段（名称/类型/分类/描述）+ 一个可编辑的 YAML 文本块承载其余
 * 全部结构字段（params_schema/ports/children/edges/segments/weights/ops/
 * state/config/file/notes/formula）。保存以 YAML 为准，走 apply-yaml。
 */
import { ref, watch, onMounted } from 'vue'
import { useAnatomyStore } from '@/stores/anatomy'

const props = defineProps<{
  form: any
  mode: 'create' | 'edit'
}>()
const emit = defineEmits<{
  close: []
  saved: []
}>()

const store = useAnatomyStore()
const yamlText = ref('')
const loading = ref(false)

// 基础字段（由用户在顶部编辑），与 yamlText 相互独立；
// 保存时以 yamlText + 覆盖基础字段为准。
async function load() {
  loading.value = true
  try {
    if (props.mode === 'edit' && props.form?.id) {
      yamlText.value = await store.fetchBlockYaml(props.form.id)
    } else {
      yamlText.value = await store.fetchYamlTemplate(props.form?.kind || 'atomic')
      // 用表单已有名称/分类/描述替换模板
      yamlText.value = applyBasics(yamlText.value, props.form)
    }
  } finally {
    loading.value = false
  }
}

// 把基础字段(名称/分类/描述)覆盖进 yaml 文本（编辑时也同步，若模板里没有则插入）
function applyBasics(text: string, f: any): string {
  let t = text
  const set = (lineRe: RegExp, val: string) => {
    const m = t.match(lineRe)
    if (m) {
      t = t.replace(lineRe, (orig: string) => {
        // 保持缩进
        const indent = orig.match(/^\s*/)![0]
        return `${indent}${val}`
      })
    } else {
      // 插到 name 之后
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
  if (!yamlText.value.trim()) {
    store.saveViaYaml('')  // 触发空内容 toast
    return
  }
  loading.value = true
  const ok = await store.saveViaYaml(yamlText.value)
  loading.value = false
  if (ok) emit('saved')
}
</script>

<template>
  <div class="modal-backdrop" @click="emit('close')">
    <div class="modal" @click.stop style="max-width:820px;width:94%;">
      <div class="modal-header">
        <h3>{{ (mode === 'create' ? '新建' : '编辑') + (props.form.kind === 'composite' ? '层' : '算子') }}</h3>
        <button class="modal-close" @click="emit('close')">✕</button>
      </div>
      <div class="modal-body form-stack">
        <div class="grid-2">
          <div class="field"><label class="form-label form-label-required">名称</label><input class="input w-100" v-model="form.name" placeholder="如 VocabParallelEmbedding"></div>
          <div class="field">
            <label class="form-label">类型</label>
            <select class="select w-100" v-model="form.kind">
              <option value="atomic">Atomic（原子算子）</option>
              <option value="composite">Composite（组合算子）</option>
            </select>
          </div>
        </div>
        <div class="grid-2">
          <div class="field"><label class="form-label">分类</label><input class="input w-100" v-model="form.category" placeholder="如 embedding"></div>
          <div class="field"><label class="form-label">描述</label><input class="input w-100" v-model="form.description"></div>
        </div>

        <div class="field">
          <label class="form-label">YAML（唯一数据源，编辑型号结构字段）</label>
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
.yaml-area { min-height: 46vh; font-size: 13px; line-height: 1.55; tab-size: 2; }
</style>