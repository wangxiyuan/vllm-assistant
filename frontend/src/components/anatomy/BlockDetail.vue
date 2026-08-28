<script setup lang="ts">
/**
 * BlockDetail.vue —— 算子详情弹窗（只读）
 * 展示 kind/category/描述/端口/参数 schema/vllm 引用。
 */
import { computed } from 'vue'

const props = defineProps<{
  block: any
}>()
const emit = defineEmits<{
  close: []
  edit: []
  del: []
}>()

const paramRows = computed(() => {
  const j = props.block?.params_schema?.properties || {}
  return Object.entries(j).map(([name, def]) => ({ name, def: def as any }))
})
const portRows = computed(() => {
  const p = props.block?.ports || {}
  return { inputs: p.inputs || [], outputs: p.outputs || [] }
})
const formulas = computed(() => props.block?.formula || [])
</script>

<template>
  <div class="modal-backdrop" @click="emit('close')">
    <div class="modal" @click.stop style="max-width:680px;width:92%;">
      <div class="modal-header">
        <h3>
          <span>{{ block.name }}</span>
          <span class="badge" :class="block.kind === 'atomic' ? 'badge-info' : 'badge-warning'">{{ block.kind }}</span>
          <span class="badge ml-1">{{ block.category }}</span>
        </h3>
        <button class="modal-close" @click="emit('close')">✕</button>
      </div>
      <div class="modal-body form-stack">
        <p v-if="block.description" class="op-detail-desc">{{ block.description }}</p>

        <!-- 计算公式 -->
        <div v-if="formulas.length" class="field">
          <label class="form-label">计算公式</label>
          <div class="op-formula">
            <div v-for="(f, i) in formulas" :key="i" class="op-formula-line">{{ f }}</div>
          </div>
        </div>

        <!-- Ports -->
        <div class="port-block" v-if="portRows.inputs.length || portRows.outputs.length">
          <div class="port-col">
            <div class="port-col-title">输入</div>
            <div v-for="p in portRows.inputs" :key="p.id" class="port-row is-in">
              <span class="port-id">{{ p.id }}</span>
              <span class="port-shape">{{ p.shape || '' }}</span>
              <span class="port-dtype">{{ p.dtype || '' }}</span>
            </div>
          </div>
          <div class="port-col">
            <div class="port-col-title">输出</div>
            <div v-for="p in portRows.outputs" :key="p.id" class="port-row is-out">
              <span class="port-id">{{ p.id }}</span>
              <span class="port-shape">{{ p.shape || '' }}</span>
              <span class="port-dtype">{{ p.dtype || '' }}</span>
            </div>
          </div>
        </div>

        <!-- Params -->
        <div v-if="paramRows.length" class="field">
          <label class="form-label">参数</label>
          <table class="op-params-table">
            <thead><tr><th>参数</th><th>类型</th><th>默认</th><th>来源</th></tr></thead>
            <tbody>
              <tr v-for="r in paramRows" :key="r.name">
                <td>{{ r.name }}</td>
                <td>{{ r.def.type || '-' }}</td>
                <td>{{ r.def.default !== undefined ? r.def.default : '-' }}</td>
                <td class="op-param-desc">{{ r.def.source || r.def.config || r.def.description || '' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- vllm -->
        <div v-if="block.file" class="field">
          <label class="form-label">实现</label>
          <div class="vllm-ref">
            <div class="vllm-file">{{ block.file }}</div>
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-danger" @click="emit('del')">删除</button>
        <span class="flex-1"></span>
        <button class="btn" @click="emit('close')">关闭</button>
        <button class="btn btn-primary" @click="emit('edit')">编辑</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.port-block { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.port-col { border: 1px solid var(--border-faint); border-radius: var(--radius-sm, 8px); padding: 8px; }
.port-col-title { font-size: 15px; color: var(--text-tertiary); text-transform: uppercase; margin-bottom: 6px; }
.port-row { display: flex; gap: 6px; font-family: var(--font-mono); font-size: 15px; padding: 2px 0; }
.port-row.is-in .port-id { color: var(--signal-blue, #5aa9e6); }
.port-row.is-out .port-id { color: var(--signal-green, #7ec8a2); }
.port-id { font-weight: 600; }
.port-shape { color: var(--text-secondary); }
.port-dtype { color: var(--text-tertiary); }
.vllm-ref { font-family: var(--font-mono); font-size: 15px; display: flex; flex-direction: column; gap: 2px; }
.op-formula { display: flex; flex-direction: column; gap: 4px; background: var(--bg-base); border: 1px solid var(--border-faint); border-radius: var(--radius-sm); padding: 8px; }
.op-formula-line { font-family: var(--font-mono); font-size: 15px; color: var(--signal-blue, #5aa9e6); white-space: pre-wrap; word-break: break-all; line-height: 1.5; }
.vllm-class { color: var(--amber); font-weight: 600; }
.vllm-file { color: var(--text-tertiary); }
</style>