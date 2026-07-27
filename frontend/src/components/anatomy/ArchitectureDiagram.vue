<script setup lang="ts">
/**
 * ArchitectureDiagram.vue - SVG model architecture pipeline diagram
 *
 * Renders the model's architecture stages as a vertical flow of SVG nodes
 * with arrows, repeat-block collapse/expand, and hover tooltips.
 *
 * Props:
 *   architecture: any[]  - model.architecture from the API
 *   operators: any[]     - full operator list (for shape info lookup)
 *
 * Emits:
 *   operatorClick(operatorId: number) - when an operator node is clicked
 */

import { computed, reactive, ref } from 'vue'

interface LayoutNode {
  key: string
  type: 'operator' | 'repeat_block'
  x: number
  y: number
  width: number
  height: number
  name?: string
  label?: string
  params?: Record<string, any>
  inputShape?: string
  outputShape?: string
  operatorId?: number | null
  // Repeat block specific
  index?: number
  repeatCount?: number
  collapsed?: boolean
  // Child node specific
  parentIndex?: number
}

interface Arrow {
  path: string
}

const props = defineProps<{
  architecture: any[]
  operators: any[]
}>()

const emit = defineEmits<{
  operatorClick: [operatorId: number]
}>()

// ── Layout constants ──
const PADDING = 24
const NODE_W = 168
const NODE_H = 44
const BLOCK_W = 200
const BLOCK_HEADER_H = 36
const INNER_NODE_W = 156
const INNER_NODE_H = 40
const GAP_Y = 28
const INNER_GAP_Y = 20
const INNER_PAD = 12

// ── State ──
const collapsedBlocks = reactive(new Set<number>())
const hoveredNode = ref<LayoutNode | null>(null)
const tooltipPos = ref({ x: 0, y: 0 })
const wrapperEl = ref<HTMLElement | null>(null)

function toggleBlock(index: number) {
  if (collapsedBlocks.has(index)) {
    collapsedBlocks.delete(index)
  } else {
    collapsedBlocks.add(index)
  }
}

function isCollapsed(index: number): boolean {
  return collapsedBlocks.has(index)
}

function getShapeInfo(operatorId: number | null) {
  if (!operatorId) return { inputShape: '', outputShape: '' }
  const op = props.operators.find((o: any) => o.id === operatorId)
  return {
    inputShape: op?.input_shape_desc || '',
    outputShape: op?.output_shape_desc || '',
  }
}

function getOperatorName(operatorId: number | null): string {
  if (!operatorId) return '未知'
  const op = props.operators.find((o: any) => o.id === operatorId)
  return op?.display_name || op?.name || '未知'
}

// Truncate text for display inside a node; full text shown in tooltip.
function truncate(text: string, maxLen: number): string {
  if (!text) return text
  return text.length > maxLen ? text.slice(0, maxLen - 1) + '…' : text
}

// ── Layout computation ──
const layout = computed(() => {
  const nodes: LayoutNode[] = []
  const arrows: Arrow[] = []
  let y = PADDING
  // Fixed content width keeps the SVG narrow so width:100% doesn't blow it up.
  const contentW = BLOCK_W
  const svgWidth = contentW + PADDING * 2

  function centerX(width: number): number {
    return (svgWidth - width) / 2
  }

  for (let i = 0; i < props.architecture.length; i++) {
    const stage = props.architecture[i]

    if (stage.type === 'operator') {
      const x = centerX(NODE_W)
      const shapeInfo = getShapeInfo(stage.operator_id)
      const prevNode = nodes[nodes.length - 1]
      if (prevNode) {
        arrows.push(computeArrow(prevNode, { x, y, width: NODE_W, height: NODE_H }))
      }
      nodes.push({
        key: `op-${i}`,
        type: 'operator',
        x,
        y,
        width: NODE_W,
        height: NODE_H,
        name: truncate(stage.operator_name || getOperatorName(stage.operator_id), 20),
        label: stage.label ? truncate(stage.label, 22) : undefined,
        params: stage.params,
        operatorId: stage.operator_id,
        inputShape: shapeInfo.inputShape,
        outputShape: shapeInfo.outputShape,
      })
      y += NODE_H + GAP_Y
    } else if (stage.type === 'repeat_block') {
      const collapsed = isCollapsed(i)
      const innerStages = stage.contents?.[0] || []
      const innerCount = innerStages.length

      const innerNodes: LayoutNode[] = []
      let innerTotalH = 0
      if (!collapsed && innerCount > 0) {
        let iy = y + BLOCK_HEADER_H + INNER_PAD
        for (let j = 0; j < innerCount; j++) {
          const innerOp = innerStages[j]
          const shapeInfo = getShapeInfo(innerOp.operator_id)
          innerNodes.push({
            key: `repeat-${i}-${j}`,
            type: 'operator',
            x: centerX(INNER_NODE_W),
            y: iy,
            width: INNER_NODE_W,
            height: INNER_NODE_H,
            name: truncate(innerOp.operator_name || getOperatorName(innerOp.operator_id), 20),
            label: innerOp.label ? truncate(innerOp.label, 22) : undefined,
            params: innerOp.params,
            operatorId: innerOp.operator_id,
            inputShape: shapeInfo.inputShape,
            outputShape: shapeInfo.outputShape,
            parentIndex: i,
          })
          iy += INNER_NODE_H + INNER_GAP_Y
        }
        innerTotalH = innerCount * INNER_NODE_H + (innerCount - 1) * INNER_GAP_Y + INNER_PAD * 2
      }

      const blockH = BLOCK_HEADER_H + innerTotalH
      const bx = centerX(BLOCK_W)
      const prevNode = nodes[nodes.length - 1]
      if (prevNode) {
        arrows.push(computeArrow(prevNode, { x: bx, y, width: BLOCK_W, height: BLOCK_HEADER_H }))
      }

      nodes.push({
        key: `block-${i}`,
        type: 'repeat_block',
        x: bx,
        y,
        width: BLOCK_W,
        height: blockH,
        name: stage.label || '重复块',
        index: i,
        repeatCount: stage.repeat_count || 1,
        collapsed,
      })

      if (!collapsed) {
        for (const inn of innerNodes) {
          nodes.push(inn)
        }
      }

      y += blockH + GAP_Y
    }
  }

  return {
    nodes,
    arrows,
    svgWidth,
    svgHeight: y + PADDING,
  }
})

function computeArrow(from: LayoutNode | { x: number; y: number; width: number; height: number }, to: { x: number; y: number; width: number; height: number }): Arrow {
  const x1 = from.x + from.width / 2
  const y1 = from.y + from.height
  const x2 = to.x + to.width / 2
  const y2 = to.y
  const midY = (y1 + y2) / 2
  return {
    path: `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`,
  }
}

// ── Hover handlers ──
// Tooltip is teleported to <body> and uses position:fixed, so we store
// viewport coordinates directly (no offset from the wrapper).
function onNodeHover(node: LayoutNode, event: MouseEvent) {
  if (node.type === 'operator') {
    hoveredNode.value = node
    tooltipPos.value = {
      x: event.clientX,
      y: event.clientY,
    }
  }
}

function onNodeLeave() {
  hoveredNode.value = null
}

function onSvgMouseMove(event: MouseEvent) {
  if (hoveredNode.value) {
    tooltipPos.value = {
      x: event.clientX,
      y: event.clientY,
    }
  }
}

// ── Click handler ──
function onNodeClick(node: LayoutNode) {
  if (node.type === 'operator' && node.operatorId) {
    emit('operatorClick', node.operatorId)
  }
}

// Width of the amber repeat-count pill based on digit count.
function repeatBadgeWidth(count: number | undefined): number {
  const len = String(count ?? 1).length
  return 22 + len * 6
}
</script>

<template>
  <div
    ref="wrapperEl"
    class="arch-wrapper"
    @mousemove="onSvgMouseMove"
  >
    <svg
      v-if="layout.nodes.length > 0"
      class="arch-svg"
      :viewBox="`0 0 ${layout.svgWidth} ${layout.svgHeight}`"
      preserveAspectRatio="xMidYMid meet"
    >
      <defs>
        <marker
          id="arrowhead"
          markerWidth="8"
          markerHeight="6"
          refX="8"
          refY="3"
          orient="auto"
        >
          <polygon points="0 0, 8 3, 0 6" fill="var(--text-tertiary)" opacity="0.5" />
        </marker>
      </defs>

      <!-- Arrows -->
      <path
        v-for="(arrow, i) in layout.arrows"
        :key="'arrow-' + i"
        :d="arrow.path"
        class="arch-arrow"
        marker-end="url(#arrowhead)"
      />

      <!-- Nodes -->
      <g
        v-for="node in layout.nodes"
        :key="node.key"
        class="arch-node"
        :class="{
          'arch-node-inner': node.parentIndex !== undefined,
          'arch-node-clickable': node.type === 'operator' && node.operatorId,
        }"
        @mouseenter="onNodeHover(node, $event)"
        @mouseleave="onNodeLeave"
        @click="onNodeClick(node)"
      >
        <!-- Repeat block background -->
        <template v-if="node.type === 'repeat_block'">
          <rect
            :x="node.x"
            :y="node.y"
            :width="node.width"
            :height="node.height"
            class="arch-block-bg"
            rx="7"
            ry="7"
          />
          <!-- Block header accent line -->
          <line
            :x1="node.x + 2"
            :y1="node.y + 7"
            :x2="node.x + 2"
            :y2="node.y + node.height - 7"
            class="arch-block-accent"
            stroke-width="2"
          />
        </template>

        <!-- Operator rect -->
        <template v-else>
          <rect
            :x="node.x"
            :y="node.y"
            :width="node.width"
            :height="node.height"
            class="arch-op-bg"
            rx="5"
            ry="5"
          />
        </template>

        <!-- Operator name -->
        <text
          :x="node.x + node.width / 2"
          :y="node.y + (node.type === 'repeat_block' ? 18 : 17)"
          class="arch-text-name"
        >
          {{ node.name }}
        </text>

        <!-- Label (operator only) -->
        <text
          v-if="node.label && node.type === 'operator'"
          :x="node.x + node.width / 2"
          :y="node.y + 31"
          class="arch-text-label"
        >
          {{ node.label }}
        </text>

        <!-- Repeat count pill (left side of block header) -->
        <template v-if="node.type === 'repeat_block'">
          <rect
            :x="node.x + 8"
            :y="node.y + 8"
            :width="repeatBadgeWidth(node.repeatCount)"
            height="16"
            rx="8"
            class="arch-repeat-pill"
          />
          <text
            :x="node.x + 8 + repeatBadgeWidth(node.repeatCount) / 2"
            :y="node.y + 18"
            class="arch-repeat-pill-text"
            text-anchor="middle"
          >
            {{ node.repeatCount }}×
          </text>
        </template>

        <!-- Collapse/expand button for repeat block -->
        <g
          v-if="node.type === 'repeat_block' && node.index !== undefined"
          class="arch-collapse-btn"
          @click.stop="toggleBlock(node.index!)"
        >
          <rect
            :x="node.x + node.width - 26"
            :y="node.y + 6"
            width="18"
            height="18"
            rx="3"
            class="arch-collapse-bg"
          />
          <text
            :x="node.x + node.width - 17"
            :y="node.y + 19"
            class="arch-collapse-icon"
            text-anchor="middle"
          >
            {{ node.collapsed ? '▶' : '▼' }}
          </text>
        </g>
      </g>
    </svg>

    <div
      v-if="layout.nodes.length === 0"
      class="arch-empty"
    >
      暂无架构数据
    </div>

    <!-- Tooltip -->
    <Teleport to="body">
      <div
        v-if="hoveredNode"
        class="arch-tooltip"
        :style="{
          left: tooltipPos.x + 'px',
          top: tooltipPos.y + 'px',
        }"
      >
        <div class="arch-tooltip-title">{{ hoveredNode.name }}</div>
        <div v-if="hoveredNode.label" class="arch-tooltip-sub">{{ hoveredNode.label }}</div>
        <div v-if="hoveredNode.inputShape" class="arch-tooltip-row">
          <span class="arch-tooltip-key arch-tooltip-shape-in">in:</span>
          <span class="arch-tooltip-val">{{ hoveredNode.inputShape }}</span>
        </div>
        <div v-if="hoveredNode.outputShape" class="arch-tooltip-row">
          <span class="arch-tooltip-key arch-tooltip-shape-out">out:</span>
          <span class="arch-tooltip-val">{{ hoveredNode.outputShape }}</span>
        </div>
        <div
          v-if="hoveredNode.params && Object.keys(hoveredNode.params).length > 0"
          class="arch-tooltip-params"
        >
          <div
            v-for="(val, key) in hoveredNode.params"
            :key="key"
            class="arch-tooltip-row"
          >
            <span class="arch-tooltip-key">{{ key }}:</span>
            <span class="arch-tooltip-val">{{ val }}</span>
          </div>
        </div>
        <div v-if="hoveredNode.operatorId" class="arch-tooltip-hint">点击查看算子详情</div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.arch-wrapper {
  position: relative;
  background: var(--bg-base);
  border: 1px solid var(--border-faint);
  border-radius: var(--radius-md);
  overflow: auto;
  padding: 8px;
  max-height: 560px;
}

.arch-svg {
  display: block;
  /* Cap the rendered height so the diagram never dominates the panel.
     The viewBox aspect ratio is preserved via preserveAspectRatio. */
  max-height: 520px;
  margin: 0 auto;
}

.arch-arrow {
  fill: none;
  stroke: var(--text-tertiary);
  stroke-width: 1.5;
  opacity: 0.45;
}

.arch-node {
  transition: opacity var(--t-fast);
}

.arch-node-clickable {
  cursor: pointer;
}

.arch-node:hover {
  filter: drop-shadow(0 0 6px var(--amber-glow));
}

.arch-op-bg {
  fill: var(--bg-elev-2);
  stroke: var(--border);
  stroke-width: 1;
  transition: stroke var(--t-base), fill var(--t-base);
}

.arch-node-clickable:hover .arch-op-bg {
  stroke: var(--amber-dim);
  fill: var(--bg-elev-3);
}

.arch-block-bg {
  fill: var(--bg-elev-1);
  stroke: var(--amber-faint);
  stroke-width: 1;
  stroke-dasharray: 5 3;
  transition: stroke var(--t-base);
}

.arch-node:hover .arch-block-bg {
  stroke: var(--amber);
}

.arch-block-accent {
  stroke: var(--amber);
  opacity: 0.4;
}

.arch-text-name {
  fill: var(--text-primary);
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  text-anchor: middle;
  dominant-baseline: central;
}

.arch-text-label {
  fill: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: 9px;
  text-anchor: middle;
  dominant-baseline: central;
}

.arch-repeat-pill {
  fill: var(--amber);
  opacity: 0.9;
}

.arch-repeat-pill-text {
  fill: var(--text-on-accent);
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 700;
  dominant-baseline: central;
}

.arch-collapse-btn {
  cursor: pointer;
}

.arch-collapse-bg {
  fill: var(--bg-elev-3);
  stroke: var(--border-faint);
  stroke-width: 1;
  transition: stroke var(--t-base), fill var(--t-base);
}

.arch-collapse-btn:hover .arch-collapse-bg {
  fill: var(--bg-elev-4);
  stroke: var(--amber-dim);
}

.arch-collapse-icon {
  fill: var(--amber);
  font-family: var(--font-mono);
  font-size: 9px;
  dominant-baseline: central;
}

.arch-empty {
  padding: 24px;
  text-align: center;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
}

.arch-tooltip {
  position: fixed;
  z-index: var(--z-tooltip);
  pointer-events: none;
  background: var(--bg-elev-4);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px 12px;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  white-space: nowrap;
  box-shadow: var(--shadow-lg);
  line-height: 1.6;
  max-width: 360px;
  /* Offset above-right of the cursor (which is at left/top) */
  transform: translate(14px, calc(-100% - 14px));
}

.arch-tooltip-title {
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
  font-size: var(--text-base);
}

.arch-tooltip-sub {
  color: var(--text-tertiary);
  font-size: var(--text-xs);
  margin-bottom: 4px;
}

.arch-tooltip-params {
  margin-top: 4px;
  padding-top: 4px;
  border-top: 1px solid var(--border-faint);
}

.arch-tooltip-row {
  display: flex;
  gap: 6px;
}

.arch-tooltip-key {
  color: var(--text-tertiary);
}

.arch-tooltip-shape-in {
  color: var(--signal-blue);
}

.arch-tooltip-shape-out {
  color: var(--signal-green);
}

.arch-tooltip-val {
  color: var(--amber-bright);
}

.arch-tooltip-hint {
  margin-top: 6px;
  padding-top: 4px;
  border-top: 1px solid var(--border-faint);
  font-size: var(--text-xs);
  color: var(--amber);
  font-family: var(--font-ui);
}
</style>
