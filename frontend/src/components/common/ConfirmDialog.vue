<script setup lang="ts">
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()

function toggleKnowledgeSync() {
  appStore.confirmDialog.knowledgeSyncChecked = !appStore.confirmDialog.knowledgeSyncChecked
}
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
          <div v-if="appStore.confirmDialog.showKnowledgeSyncCheckbox" class="knowledge-sync-checkbox" style="margin-top: 12px;">
            <label class="checkbox-label">
              <input
                type="checkbox"
                :checked="appStore.confirmDialog.knowledgeSyncChecked"
                @change="toggleKnowledgeSync"
              />
              <span>是否同步删除知识库内容</span>
            </label>
          </div>
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
