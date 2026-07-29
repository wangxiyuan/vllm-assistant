<script setup lang="ts">
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()
</script>

<template>
  <Teleport to="body">
    <div v-if="appStore.confirmDialog.show" class="modal-backdrop confirm-backdrop" @click="appStore.confirmCancel()">
      <div class="modal confirm-modal" @click.stop>
        <div class="modal-header">
          <h3>{{ appStore.confirmDialog.title }}</h3>
        </div>
        <div class="modal-body">
          <p class="modal-desc" style="padding:0;">{{ appStore.confirmDialog.message }}</p>
        </div>
        <div class="modal-footer">
          <button class="btn" @click="appStore.confirmCancel()">{{ appStore.confirmDialog.cancelText }}</button>
          <button class="btn" :class="appStore.confirmDialog.danger ? 'btn-danger' : 'btn-primary'"
                  @click="appStore.confirmOk()">{{ appStore.confirmDialog.confirmText }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
