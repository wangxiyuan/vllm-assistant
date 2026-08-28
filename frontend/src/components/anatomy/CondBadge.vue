<script setup lang="ts">
/**
 * CondBadge.vue —— 条件表达式徽章（右上凸出 ribbon）
 * 由父级对 condition 求值后传入 truthy；本组件纯展示。
 *   truthy === true  -> 生效（绿）
 *   truthy === false -> 未生效/显隐（红）
 *   truthy === null  -> 未求值（灰,虚线）
 */
const props = defineProps<{
  expr: string
  truthy?: boolean | null
}>()
</script>

<template>
  <span class="cb" :class="{ t: truthy === true, f: truthy === false, u: truthy === null }"
        :title="truthy === true ? '条件满足，该节点生效' : (truthy === false ? '条件不满足，默认不引入' : '条件无法求值（缺少相关 config）')">
    <span class="cb-if">if</span>
    <span class="cb-expr">{{ expr }}</span>
    <span class="cb-mark" v-if="truthy === true">✓</span>
    <span class="cb-mark" v-else-if="truthy === false">✗</span>
    <span class="cb-mark" v-else>?</span>
  </span>
</template>

<style scoped>
.cb {
  display: inline-flex; align-items: center; gap: 0.28em;
  font-family: var(--font-mono); font-size: 0.66em; font-weight: 600;
  padding: 0.12em 0.5em 0.12em 0.4em; border-radius: 0 0.35em 0 0.35em;
  max-width: 100%;
}
.cb-if { text-transform: uppercase; letter-spacing: 0.04em; opacity: 0.85; }
.cb-expr { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; word-break: break-all; }
.cb-mark { flex: none; font-weight: 800; }

/* 真：绿实色 */
.cb.t { background: var(--signal-green-glow, rgba(142,236,151,0.14)); color: var(--signal-green, #8eec97); border: 1px solid var(--signal-green, #8eec97); }
/* 假：红实色 */
.cb.f { background: var(--signal-red-glow, rgba(255,142,133,0.14)); color: var(--signal-red, #ff8e85); border: 1px solid var(--signal-red, #ff8e85); }
/* 未知：灰虚线 */
.cb.u { background: var(--bg-elev-3); color: var(--text-tertiary); border: 1px dashed var(--border-bright, #4d5a72); }
</style>