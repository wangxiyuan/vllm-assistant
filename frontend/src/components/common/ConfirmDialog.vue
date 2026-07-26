<script setup lang="ts">
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()
</script>

<template>
  <Teleport to="body">
    <div v-if="appStore.confirmDialog.show" class="modal-backdrop" @click="appStore.confirmCancel()">
      <div class="modal confirm-modal" @click.stop>
        <h3 class="modal-title">{{ appStore.confirmDialog.title }}</h3>
        <p class="modal-desc">{{ appStore.confirmDialog.message }}</p>
        <div class="modal-actions">
          <button class="btn" @click="appStore.confirmCancel()">{{ appStore.confirmDialog.cancelText }}</button>
          <button class="btn" :class="{ 'btn-danger': appStore.confirmDialog.danger }"
                  @click="appStore.confirmOk()">{{ appStore.confirmDialog.confirmText }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
