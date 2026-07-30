<script setup lang="ts">
defineProps<{
  label: string
}>()
</script>

<template>
  <div class="filter-row">
    <span class="filter-row-label">{{ label }}</span>
    <div class="filter-row-content">
      <slot />
    </div>
  </div>
</template>