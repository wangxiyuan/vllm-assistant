<script setup lang="ts">
/**
 * AssemblyDiagram.vue —— 模型组装结构树（递归展开）
 *
 * 递归展开 assembly steps + 引用的 assembly / composite children，
 * 用 AssemblyTreeNode 渲染任意深度。
 */
import { computed } from 'vue'
import AssemblyTreeNode from '@/components/anatomy/AssemblyTreeNode.vue'
import { resolveLoopCount, evalCondition } from '@/utils/resolveConfig'
import type { AnatomyBlock, ModelAssembly } from '@/utils/types'

const props = defineProps<{
  definition: any
  config?: any
  blocks: any[]
  assemblies?: any[]
}>()

interface RNode {
  key: string
  label: string
  blockName?: string
  kind?: string
  state?: string
  condition?: string
  conditionTruthy?: boolean | null
  role?: string
  depth: number
  loopCount?: string
  children: RNode[]
}

function blockOf(name?: string): AnatomyBlock | undefined {
  return props.blocks.find(b => b.name === name)
}
function assemblyOf(name?: string): ModelAssembly | undefined {
  return (props.assemblies || []).find(a => a.name === name)
}
// 求值用的 config：优先按被引用 assembly/block 自带 config（须非空），否则用顶层
function configFor(name?: string): Record<string, any> {
  const asm = assemblyOf(name)
  if (asm?.config && Object.keys(asm.config).length) return asm.config
  const blk = blockOf(name)
  if (blk?.config && Object.keys(blk.config).length) return blk.config
  return props.config || {}
}

let uid = 0
function build(definition: any = {}, selfName?: string): RNode[] {
  const steps = definition.steps || []
  const children = definition.children || []
  const nodes: RNode[] = []
  for (const s of steps) {
    const blk = blockOf(s.block)
    const asm = assemblyOf(s.block)
    const loop = s.loop ? resolveLoopCount(s.loop.count, configFor(s.block)) : null
    const node: RNode = {
      key: 'n' + (++uid),
      label: s.as || s.id || s.block || '',
      blockName: s.block,
      kind: asm ? 'assembly' : (blk?.kind || 'atomic'),
      state: s.condition ? 'cond' : (s.loop ? 'loop' : 'active'),
      condition: s.condition,
      conditionTruthy: s.condition ? evalCondition(s.condition, configFor(s.block)).truthy : null,
      depth: 0,
      loopCount: loop && loop.ok ? loop.label : (s.loop?.count != null ? String(s.loop.count) : undefined),
      children: [],
    }
    if (asm) {
      node.children = build(asm.definition, s.block)
    } else if (blk?.kind === 'composite') {
      node.children = build({ children: blk.children }, s.block)
    }
    nodes.push(node)
  }
  for (const c of children) {
    const blk = blockOf(c.block)
    const asm = assemblyOf(c.block)
    const node: RNode = {
      key: 'n' + (++uid),
      label: c.id || c.block || '',
      blockName: c.block,
      kind: asm ? 'assembly' : (blk?.kind || 'atomic'),
      state: c.condition ? 'cond' : 'active',
      condition: c.condition,
      conditionTruthy: c.condition ? evalCondition(c.condition, configFor(c.block)).truthy : null,
      role: c.role, depth: 0,
      children: [],
    }
    if (asm) node.children = build(asm.definition, c.block)
    else if (blk?.kind === 'composite') node.children = build({ children: blk.children }, c.block)
    nodes.push(node)
  }
  return nodes
}

const tree = computed<RNode[]>(() => build(props.definition))
function countAll(): number {
  let n = 0
  const walk = (ns: any[]) => { for (const x of ns) { n++; walk(x.children) } }
  walk(tree.value)
  return n
}
</script>

<template>
  <div class="adiag3">
    <div class="adiag3-toolbar" v-if="tree.length">
      <span class="adiag3-count">{{ tree.length }} 顶层 · {{ countAll() }} 节点</span>
    </div>
    <div class="adiag3-tree">
      <AssemblyTreeNode v-for="node in tree" :key="node.key" :node="node" />
      <div v-if="tree.length === 0" class="adiag3-empty">暂无构成</div>
    </div>
  </div>
</template>

<style scoped>
.adiag3 { border: 1px solid var(--border-faint); border-radius: var(--radius-md); min-height: 120px; padding: var(--space-3); background: var(--bg-base); }
.adiag3-toolbar { font-family: var(--font-mono); font-size: 15px; color: var(--text-tertiary); margin-bottom: var(--space-2); }
.adiag3-tree { display: flex; flex-direction: column; gap: 1px; }
.adiag3-empty { color: var(--text-tertiary); text-align: center; padding: 32px; font-family: var(--font-mono); font-size: 15px; }
</style>