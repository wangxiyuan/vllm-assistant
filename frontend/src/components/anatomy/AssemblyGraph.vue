<script setup lang="ts">
/**
 * AssemblyGraph.vue —— 模型组装图视图（思维导图式）
 *
 * 递归展开 steps / children，以及引用的 composite / assembly。
 * 布局：根在左、子往右，逐层展开（思维导图风格），loop count 解析为具体数值。
 */
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import MindRoot from '@/components/anatomy/MindRoot.vue'
import { resolveLoopCount, evalCondition } from '@/utils/resolveConfig'
import type { AnatomyBlock, ModelAssembly } from '@/utils/types'

const props = defineProps<{
  definition: any
  config?: any
  blocks: any[]
  assemblies?: any[]
  isAssembly?: boolean
}>()

const expandAll = ref(false)

function blockOf(name?: string): AnatomyBlock | undefined {
  return props.blocks.find(b => b.name === name)
}
function assemblyOf(name?: string): ModelAssembly | undefined {
  return (props.assemblies || []).find(a => a.name === name)
}

// 求值用的 config：优先按被引用的 assembly/block 名匹配其自带 config（须非空），否则用顶层 config
function configFor(name?: string): Record<string, any> {
  const asm = assemblyOf(name)
  if (asm?.config && Object.keys(asm.config).length) return asm.config
  const blk = blockOf(name)
  if (blk?.config && Object.keys(blk.config).length) return blk.config
  return props.config || {}
}

const isSinkId = (id: string) => ['out', 'y', 'logits', 'hidden_out', 'output'].includes(id)
const isSourceId = (id: string) => ['input_ids', 'x', 'input', 'hidden_states_in', 'positions'].includes(id)

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

// 递归展开
function expandList(list: any[], depth: number): MNode[] {
  if (!list) return []
  return list.map((e: any) => {
    const blk = blockOf(e.block)
    const asm = assemblyOf(e.block)
    const childrenRaw = asm?.definition?.steps || blk?.children || e.children || []
    const kind = asm ? 'assembly' : (blk?.kind || 'atomic')
    const loop = e.loop ? resolveLoopCount(e.loop.count, configFor(e.block)) : null
    const node: MNode = {
      id: (asm ? 'asm:' : 'blk:') + (e.id || e.block || '') + ':' + depth,
      label: e.as || e.id || e.block || '',
      blockName: e.block,
      kind,
      loopCount: loop && loop.ok ? loop.label : (e.loop?.count != null ? String(e.loop.count) : (e.repeat_count != null ? String(e.repeat_count) : undefined)),
      condition: e.condition,
      conditionTruthy: e.condition ? evalCondition(e.condition, configFor(e.block)).truthy : undefined,
      role: e.role,
      isSource: isSourceId(e.id), isSink: isSinkId(e.id),
    }
    const isContainer = asm || blk?.kind === 'composite'
    // 始终生成 children 数据（折叠与否只由 MindNode 的 open 控制，不在此裁剪）
    if (isContainer && childrenRaw?.length) {
      node.hasChildren = true
      node.children = expandList(childrenRaw, depth + 1)
    }
    return node
  })
}

const top = computed<MNode[]>(() => {
  const def = props.definition || {}
  const steps = def.steps
  const list = steps && steps.length ? steps : (def.children || [])
  return expandList(list, 0)
})

function countNodes(ns: MNode[]): number {
  let n = 0
  for (const x of ns) { n++; if (x.children) n += countNodes(x.children) }
  return n
}
const nodeCount = computed(() => countNodes(top.value))

// 全屏
const fullscreen = ref(false)
const rootEl = ref<HTMLElement | null>(null)
function toggleFullscreen() {
  if (document.fullscreenElement) {
    document.exitFullscreen?.()
  } else {
    rootEl.value?.requestFullscreen?.()
  }
}
function onFsChange() {
  fullscreen.value = !!document.fullscreenElement
}
onMounted(() => document.addEventListener('fullscreenchange', onFsChange))
onBeforeUnmount(() => document.removeEventListener('fullscreenchange', onFsChange))

// ===== 画布式拖拽平移 + 滚轮缩放 =====
const canvasRef = ref<HTMLElement | null>(null)
const dragging = ref(false)
const zoom = ref(1)
const pan = ref({ x: 0, y: 0 }) // 视口原点在画布内容上的偏移（缩放中心为 0,0）
const MIN_ZOOM = 0.4
const MAX_ZOOM = 3
let dragStartX = 0
let dragStartY = 0
let startPan = { x: 0, y: 0 }

function onMouseDown(e: MouseEvent) {
  // 不遮挡节点/可交互目标；从空白处按下开始平移
  const t = e.target as HTMLElement
  if (t.closest('.mn-node, .mn-toggle, button, a, input, select, textarea, .ag-toolbar')) return
  dragging.value = true
  dragStartX = e.clientX
  dragStartY = e.clientY
  startPan = { ...pan.value }
  document.body.style.cursor = 'grabbing'
  e.preventDefault()
}
function onMouseMove(e: MouseEvent) {
  if (!dragging.value) return
  // 屏幕像素级 1:1 跟随鼠标：拖拽幅度与缩放无关，始终一致
  const dx = e.clientX - dragStartX
  const dy = e.clientY - dragStartY
  pan.value = { x: startPan.x + dx, y: startPan.y + dy }
}
function onMouseUp() {
  dragging.value = false
  document.body.style.cursor = ''
}

function onWheel(e: WheelEvent) {
  e.preventDefault()
  const rect = canvasRef.value?.getBoundingClientRect()
  if (!rect) return
  // 光标在画布内的局部坐标（去除 pan 得到缩放基点内容坐标）
  const cx = e.clientX - rect.left - pan.value.x
  const cy = e.clientY - rect.top - pan.value.y
  const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15
  const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom.value * factor))
  const k = next / zoom.value
  pan.value.x = e.clientX - rect.left - cx * k
  pan.value.y = e.clientY - rect.top - cy * k
  zoom.value = next
}
// 基于根字号缩放整树（避免 transform:scale 放大发糊），同时用 font-size 做缩放反缩放 padding 使递归宽度一致
function zoomStyle() {
  return {
    fontSize: `${18 * zoom.value}px`,
    transform: `translate(${pan.value.x}px, ${pan.value.y}px)`,
  }
}
</script>

<template>
  <div class="ag" ref="rootEl" :class="{ fullscreen }">
    <div class="ag-toolbar">
      <label class="ag-expand-toggle">
        <input type="checkbox" v-model="expandAll" /> 全部展开
      </label>
      <span class="flex-1"></span>
      <span class="ag-count">{{ top.length }} 顶层 · {{ nodeCount }} 节点</span>
      <button class="ag-fs-btn" :title="fullscreen ? '退出全屏' : '全屏显示'" @click="toggleFullscreen">
        <svg v-if="!fullscreen" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>
        <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"/></svg>
      </button>
    </div>
    <div class="ag-viewport" ref="canvasRef" :class="{ dragging }"
      @mousedown.left="onMouseDown" @mousemove="onMouseMove" @mouseup="onMouseUp" @mouseleave="onMouseUp"
      @wheel.prevent="onWheel">
      <div class="ag-pan" :style="zoomStyle()">
        <MindRoot :nodes="top" :expandAll="expandAll" />
        <div v-if="top.length === 0" class="ag-empty">暂无构成</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ag { border: 1px solid var(--border-faint); border-radius: var(--radius-md); background: var(--bg-base); }
.ag.fullscreen { border: none; border-radius: 0; height: 100vh; display: flex; flex-direction: column; }
.ag.fullscreen .ag-viewport { flex: 1; max-height: none; height: auto; }
.ag-toolbar { display: flex; align-items: center; gap: 10px; padding: 6px 10px; border-bottom: 1px solid var(--border-faint); }
.ag-expand-toggle { font-size: 15px; color: var(--text-secondary); display: flex; align-items: center; gap: 4px; cursor: pointer; }
.ag-count { font-family: var(--font-mono); font-size: 15px; color: var(--text-tertiary); }
.ag-fs-btn { background: var(--bg-elev-3); border: 1px solid var(--border-faint); color: var(--text-secondary); border-radius: var(--radius-xs); width: 28px; height: 28px; display: flex; align-items: center; justify-content: center; cursor: pointer; }
.ag-fs-btn:hover { color: var(--amber); border-color: var(--amber-dim); }
.ag-viewport { position: relative; overflow: hidden; max-height: 74vh; height: 60vh; cursor: grab; background-color: rgba(0,0,0,0.15); }
.ag-viewport.dragging { cursor: grabbing; user-select: none; -webkit-user-select: none; }
.ag-pan { min-width: 0; transform-origin: 0 0; will-change: transform; line-height: 1.4; }
.ag-empty { color: var(--text-tertiary); text-align: center; padding: 32px; font-family: var(--font-mono); font-size: 15px; }
</style>