<script setup lang="ts">
/**
 * AssemblyCanvas.vue —— 模型组装画布编辑器
 *
 * 把 model_assembly.definition.steps 渲染成可编排的算子流水线：
 *   - 每个 step 是一个算子卡片，可选择算子、配置参数、标签、循环、条件
 *   - 支持拖拽排序
 *   - 显示端口输入/输出、当前校验状态
 *
 * v-model 绑定 definition 对象（{ steps, edges, ports }）+ 引用 blocks 库。
 */
import { computed, ref } from 'vue'

const props = defineProps<{
  definition: any
  blocks: any[]
}>()

const emit = defineEmits<{
  stepChange: [step: any]
  remove: [idx: number]
}>()

const steps = computed(() => props.definition?.steps || [])

function blockOf(name: string) {
  return props.blocks.find(b => b.name === name)
}

function portDisplay(block: any, dir: 'inputs' | 'outputs') {
  const ports = block?.ports?.[dir] || []
  return ports.map((p: any) => p.id + (p.shape ? ` ${p.shape}` : '')).join(' · ')
}

function onBlockChange(step: any) {
  emit('stepChange', step)
}

const dragIdx = ref<number | null>(null)
function onDragStart(i: number) { dragIdx.value = i }
function onDrop(i: number) {
  if (dragIdx.value === null || dragIdx.value === i) { dragIdx.value = null; return }
  const arr = steps.value
  const [it] = arr.splice(dragIdx.value, 1)
  arr.splice(i, 0, it)
  dragIdx.value = null
}
</script>

<template>
  <div class="asm-canvas">
    <div v-if="steps.length === 0" class="asm-canvas-empty">
      暂无步骤。左侧「+ 添加算子」开始搭建模型。
    </div>

    <div
      v-for="(step, idx) in steps"
      :key="step.id"
      class="asm-node"
      draggable="true"
      @dragstart="onDragStart(idx)"
      @dragover.prevent
      @drop.prevent="onDrop(idx)"
    >
      <!-- Step top bar -->
      <div class="asm-node-head">
        <span class="asm-node-idx">#{{ idx + 1 }}</span>
        <span class="asm-node-kind" :class="step.loop ? 'is-loop' : ''">
          {{ step.loop ? 'loop' : (blockOf(step.block)?.kind || 'step') }}
        </span>
        <span class="asm-node-label" v-if="step.as">{{ step.as }}</span>
        <span class="flex-1"></span>
        <button class="asm-node-del" title="删除" @click="$emit('remove', idx)">✕</button>
      </div>

      <!-- Step body -->
      <div class="asm-node-body">
        <!-- block dropdown -->
        <select class="input input-sm w-100" :value="step.block" @change="step.block = ($event.target as HTMLSelectElement).value; onBlockChange(step)">
          <option value="">选择算子…</option>
          <option v-for="b in blocks" :key="b.name" :value="b.name">{{ b.name }}</option>
        </select>

        <!-- as label -->
        <input class="input input-sm w-100 mt-1" type="text" v-model="step.as" placeholder="as …（可省略）" />

        <!-- ports info -->
        <div v-if="blockOf(step.block)" class="asm-ports">
          <div v-if="portDisplay(blockOf(step.block), 'inputs')" class="asm-port-row is-in">in: <span>{{ portDisplay(blockOf(step.block), 'inputs') }}</span></div>
          <div v-if="portDisplay(blockOf(step.block), 'outputs')" class="asm-port-row is-out">out: <span>{{ portDisplay(blockOf(step.block), 'outputs') }}</span></div>
        </div>

        <!-- params / port_bind -->
        <div v-if="step.port_bind && Object.keys(step.port_bind).length" class="asm-params">
          <div v-for="(val, key) in step.port_bind" :key="key" class="asm-param">
            <label>{{ key }}</label>
            <input class="input input-sm" type="text" v-model="step.port_bind[key]">
          </div>
        </div>

        <!-- loop / condition -->
        <div v-if="step.loop" class="asm-loop">
          <span class="asm-loop-badge">循环 ×{{ step.loop.count || '?' }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.asm-canvas { display: flex; flex-direction: column; gap: 10px; min-height: 200px; }
.asm-canvas-empty { padding: 32px; text-align: center; color: var(--text-tertiary); font-family: var(--font-mono); font-size: var(--text-sm); border: 1px dashed var(--border-faint); border-radius: var(--radius-md); }
.asm-node { background: var(--bg-elev-2); border: 1px solid var(--border-faint); border-radius: var(--radius-md); overflow: hidden; cursor: grab; transition: border-color var(--t-fast); }
.asm-node:hover { border-color: var(--amber-dim); }
.asm-node-head { display: flex; align-items: center; gap: 8px; padding: 6px 10px; background: var(--bg-elev-3); border-bottom: 1px solid var(--border-faint); }
.asm-node-idx { font-family: var(--font-mono); font-size: 15px; color: var(--amber); font-weight: 700; }
.asm-node-kind { font-size: 15px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-tertiary); padding: 2px 6px; background: var(--bg-elev-4); border-radius: 3px; }
.asm-node-kind.is-loop { color: var(--amber); }
.asm-node-label { font-family: var(--font-mono); font-size: 15px; color: var(--text-secondary); }
.asm-node-del { background: none; border: none; color: var(--text-tertiary); cursor: pointer; padding: 2px 4px; }
.asm-node-del:hover { color: var(--color-danger, #f4796b); }
.asm-node-body { padding: 10px; display: flex; flex-direction: column; gap: 6px; }
.mt-1 { margin-top: 6px; }
.asm-ports { font-family: var(--font-mono); font-size: 15px; display: flex; flex-direction: column; gap: 2px; }
.asm-port-row.is-in { color: var(--signal-blue, #5aa9e6); }
.asm-port-row.is-out { color: var(--signal-green, #7ec8a2); }
.asm-params { border-top: 1px solid var(--border-faint); padding-top: 6px; display: flex; flex-direction: column; gap: 4px; }
.asm-param { display: flex; align-items: center; gap: 6px; }
.asm-param label { font-family: var(--font-mono); font-size: 15px; color: var(--text-tertiary); flex: 0 0 80px; text-align: right; }
.asm-loop { border-top: 1px solid var(--border-faint); padding-top: 6px; }
.asm-loop-badge { background: var(--amber-faint); color: var(--text-on-accent, #0b0b0c); font-family: var(--font-mono); font-size: 15px; padding: 2px 8px; border-radius: 3px; }
</style>