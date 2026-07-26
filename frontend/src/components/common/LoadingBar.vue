<script setup lang="ts">
defineProps<{ visible: boolean }>()
</script>

<template>
  <div v-if="visible" class="loading-bar"></div>
</template>
