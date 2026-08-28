<script setup lang="ts">
/**
 * BlockLibrary.vue —— 构建单元库（左侧）
 *
 * 按 category 分组展示 building_block，支持搜索、点选详情。
 * kind: atomic（实块）/ composite（嵌套边框）。
 *
 * 可选 fixedKind：不传 = 顶层带「全部/原子/组合」切换（算子大类）；
 * 传入 'atomic' / 'composite' = 锁定该 kind，隐藏切换 tab（拆分的「算子」「层」tab 用）。
 * label 用于文案（默认「算子」）。
 */
import { ref, computed } from 'vue'

const props = defineProps<{
  blocks: any[]
  search: string
  categoryFilter: string
  kindFilter: 'all' | 'atomic' | 'composite'
  fixedKind?: 'all' | 'atomic' | 'composite'
  label?: string
}>()

const emit = defineEmits<{
  'update:search': [v: string]
  'update:categoryFilter': [v: string]
  'update:kindFilter': [v: 'all' | 'atomic' | 'composite']
  openDetail: [block: any]
  newBlock: []
}>()

const collapsed = ref<Set<string>>(new Set())

const effectiveKind = computed<'all' | 'atomic' | 'composite'>(
  () => props.fixedKind || props.kindFilter,
)

const filtered = computed(() => {
  let list = props.blocks
  if (props.categoryFilter) list = list.filter(b => b.category === props.categoryFilter)
  if (effectiveKind.value !== 'all') list = list.filter(b => b.kind === effectiveKind.value)
  if (props.search) {
    const q = props.search.toLowerCase()
    list = list.filter(b => b.name.toLowerCase().includes(q))
  }
  return list
})

const groups = computed(() => {
  const m = new Map<string, any[]>()
  for (const b of filtered.value) {
    const cat = b.category || 'other'
    if (!m.has(cat)) m.set(cat, [])
    m.get(cat)!.push(b)
  }
  return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]))
})

const topCategories = computed(() => {
  const m = new Map<string, number>()
  for (const b of props.blocks) {
    if (effectiveKind.value !== 'all' && b.kind !== effectiveKind.value) continue
    m.set(b.category, (m.get(b.category) || 0) + 1)
  }
  return [...m.entries()].map(([name, count]) => ({ name, count }))
})

function toggle(cat: string) {
  const s = new Set(collapsed.value)
  if (s.has(cat)) s.delete(cat); else s.add(cat)
  collapsed.value = s
}
const isCollapsed = (c: string) => collapsed.value.has(c)
</script>

<template>
  <div class="blib">
    <div class="blib-header">
      <input class="input input-sm w-100" :value="search" @input="emit('update:search', ($event.target as HTMLInputElement).value)" :placeholder="'搜索' + (label || '算子') + '…'" />
      <button class="btn btn-primary btn-xs w-100 mt-1" @click="emit('newBlock')">+ 新建{{ label || '算子' }}</button>
    </div>

    <div v-if="!fixedKind" class="blib-kinds">
      <button class="blib-kind-chip" :class="{ active: kindFilter === 'all' }" @click="emit('update:kindFilter', 'all')">全部</button>
      <button class="blib-kind-chip" :class="{ active: kindFilter === 'atomic' }" @click="emit('update:kindFilter', 'atomic')">
        <span class="blib-block-dot atomic"></span>原子算子
      </button>
      <button class="blib-kind-chip" :class="{ active: kindFilter === 'composite' }" @click="emit('update:kindFilter', 'composite')">
        <span class="blib-block-dot composite"></span>组合算子
      </button>
    </div>

    <div class="blib-cats">
      <button class="blib-cat-chip" :class="{ active: !categoryFilter }" @click="emit('update:categoryFilter', '')">全部</button>
      <button v-for="c in topCategories" :key="c.name" class="blib-cat-chip"
        :class="{ active: categoryFilter === c.name }" @click="emit('update:categoryFilter', c.name)">
        {{ c.name }}<span class="blib-cat-count">{{ c.count }}</span>
      </button>
    </div>

    <div class="blib-groups">
      <div v-for="g in groups" :key="g[0]" class="blib-group">
        <div class="blib-group-head" @click="toggle(g[0])">
          <span class="blib-chev" :class="{ collapsed: isCollapsed(g[0]) }">▸</span>
          <span class="blib-group-name">{{ g[0] }}</span>
          <span class="blib-group-count">{{ g[1].length }}</span>
        </div>
        <div v-show="!isCollapsed(g[0])" class="blib-group-body">
          <div v-for="b in g[1]" :key="b.id" class="blib-block" @click="emit('openDetail', b)">
            <span class="blib-block-dot" :class="b.kind"></span>
            <span class="blib-block-name">{{ b.name }}</span>
            <span class="blib-block-kind">{{ b.kind }}</span>
          </div>
        </div>
      </div>
      <div v-if="groups.length === 0" class="blib-empty">无匹配{{ label || '算子' }}</div>
    </div>
  </div>
</template>

<style scoped>
.blib { display: flex; flex-direction: column; gap: 10px; height: 100%; }
.blib-cats { display: flex; flex-wrap: wrap; gap: 4px; }
.blib-kinds { display: flex; gap: 4px; }
.blib-kind-chip { display: flex; align-items: center; gap: 5px; background: var(--bg-elev-2); border: 1px solid var(--border-faint); color: var(--text-secondary); font-size: 15px; padding: 4px 10px; border-radius: 6px; cursor: pointer; }
.blib-kind-chip.active { background: var(--amber-glow-soft); border-color: var(--amber-dim); color: var(--amber); font-weight: 600; }
.blib-kinds .blib-block-dot { width: 8px; height: 8px; border-radius: 2px; }
.blib-cat-chip { background: var(--bg-elev-2); border: 1px solid var(--border-faint); color: var(--text-secondary); font-size: 15px; padding: 2px 8px; border-radius: 12px; cursor: pointer; }
.blib-cat-chip.active { background: var(--amber-glow-soft); border-color: var(--amber-dim); color: var(--amber); }
.blib-cat-count { margin-left: 4px; opacity: 0.6; font-size: 15px; }
.blib-groups { flex: 1; overflow: auto; display: flex; flex-direction: column; gap: 6px; }
.blib-group-head { display: flex; align-items: center; gap: 6px; cursor: pointer; padding: 4px 2px; }
.blib-chev { transition: transform var(--t-fast); font-size: 15px; color: var(--text-tertiary); }
.blib-chev.collapsed { transform: rotate(90deg); }
.blib-group-name { font-weight: 600; font-size: 15px; color: var(--text-secondary); text-transform: capitalize; }
.blib-group-count { font-size: 15px; color: var(--text-tertiary); }
.blib-group-body { display: flex; flex-direction: column; gap: 3px; padding-left: 12px; }
.blib-block { display: flex; align-items: center; gap: 8px; padding: 6px 10px; background: var(--bg-elev-2); border: 1px solid var(--border-faint); border-radius: var(--radius-smm, 6px); cursor: pointer; }
.blib-block:hover { border-color: var(--amber-dim); background: var(--bg-elev-3); }
.blib-block-dot { width: 8px; height: 8px; border-radius: 2px; flex: none; }
.blib-block-dot.atomic { background: var(--amber); }
.blib-block-dot.composite { background: var(--signal-blue, #5aa9e6); }
.blib-block-name { font-family: var(--font-mono); font-size: 15px; color: var(--text-primary); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.blib-block-kind { font-size: 15px; text-transform: uppercase; color: var(--text-tertiary); }
.blib-empty { color: var(--text-tertiary); text-align: center; padding: 20px; font-size: 15px; }
</style>