<script setup lang="ts">
import { onMounted } from 'vue'
import { useAnatomyStore } from '@/stores/anatomy'
import { useAppStore } from '@/stores/app'
import { useUsersStore } from '@/stores/users'

const anatomyStore = useAnatomyStore()
const appStore = useAppStore()
const usersStore = useUsersStore()

onMounted(() => {
  anatomyStore.switchAnatomyTab('operators')
})
</script>

<template>
  <div class="view-container">
    <div class="view-header">
      <h2 class="view-title">模型拆解</h2>
      <div class="view-actions">
        <button class="btn btn-sm" @click="anatomyStore.openCategoryManager()">分类管理</button>
        <button v-if="anatomyStore.anatomyTab === 'operators'" class="btn btn-primary btn-sm"
                @click="anatomyStore.openNewOperator()">+ 新建算子</button>
        <button v-else class="btn btn-primary btn-sm" @click="anatomyStore.openNewModel()">+ 新建模型</button>
      </div>
    </div>

    <div class="tab-bar" style="margin-bottom:var(--space-5)">
      <button class="tab" :class="{ active: anatomyStore.anatomyTab === 'operators' }"
              @click="anatomyStore.switchAnatomyTab('operators')">算子</button>
      <button class="tab" :class="{ active: anatomyStore.anatomyTab === 'models' }"
              @click="anatomyStore.switchAnatomyTab('models')">模型</button>
    </div>

    <!-- Operators tab -->
    <template v-if="anatomyStore.anatomyTab === 'operators'">
      <div class="anatomy-filters">
        <input type="text" class="input" v-model="anatomyStore.operatorSearch" placeholder="搜索算子…" />
        <select class="select" v-model="anatomyStore.operatorFilterCategory">
          <option value="">全部分类</option>
          <option v-for="cat in anatomyStore.operatorCategoryOptions" :key="cat.value" :value="cat.value">{{ cat.label }}</option>
        </select>
      </div>

      <div class="operator-grid">
        <div v-for="op in anatomyStore.operators" :key="op.id" class="operator-card" @click="anatomyStore.viewOperatorDetail(op)">
          <h4 class="operator-name">{{ op.display_name }}</h4>
          <span class="operator-category" :style="{ color: anatomyStore.operatorCategoryOptions.find(c => c.value === op.category)?.color }">
            {{ op.category }}
          </span>
          <p v-if="op.description" class="operator-desc">{{ op.description }}</p>
        </div>
      </div>
    </template>

    <!-- Models tab -->
    <template v-if="anatomyStore.anatomyTab === 'models'">
      <div class="anatomy-filters">
        <input type="text" class="input" v-model="anatomyStore.modelSearch" placeholder="搜索模型…" />
        <select class="select" v-model="anatomyStore.modelFilterCategory">
          <option value="">全部分类</option>
          <option v-for="cat in anatomyStore.modelCategoryOptions" :key="cat.value" :value="cat.value">{{ cat.label }}</option>
        </select>
      </div>

      <div class="model-grid">
        <div v-for="model in anatomyStore.models" :key="model.id" class="model-card" @click="anatomyStore.viewModel(model)">
          <h4 class="model-name">{{ model.display_name }}</h4>
          <span class="model-category">{{ model.category }}</span>
          <p v-if="model.description" class="model-desc">{{ model.description }}</p>
        </div>
      </div>
    </template>

    <!-- Operator Detail Modal -->
    <Teleport to="body">
      <div v-if="anatomyStore.showOperatorDetail" class="modal-backdrop" @click="anatomyStore.closeOperatorDetail()">
        <div class="modal" @click.stop>
          <div class="modal-header">
            <h3>{{ anatomyStore.selectedOperator?.display_name }}</h3>
            <button class="btn btn-sm" @click="anatomyStore.editFromDetail()">编辑</button>
            <button class="btn btn-sm btn-ghost" @click="anatomyStore.closeOperatorDetail()">&times;</button>
          </div>
          <div class="modal-body">
            <p><strong>名称：</strong>{{ anatomyStore.selectedOperator?.name }}</p>
            <p><strong>分类：</strong>{{ anatomyStore.selectedOperator?.category }}</p>
            <p v-if="anatomyStore.selectedOperator?.description"><strong>描述：</strong>{{ anatomyStore.selectedOperator.description }}</p>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Operator Editor Modal -->
    <Teleport to="body">
      <div v-if="anatomyStore.showOperatorEditor" class="modal-backdrop" @click="anatomyStore.closeOperatorEditor()">
        <div class="modal modal-lg" @click.stop>
          <h3>{{ anatomyStore.operatorEditorMode === 'create' ? '新建算子' : '编辑算子' }}</h3>
          <div class="form-group">
            <input type="text" class="input" v-model="anatomyStore.operatorForm.name" placeholder="算子名称" />
          </div>
          <div class="form-group">
            <input type="text" class="input" v-model="anatomyStore.operatorForm.display_name" placeholder="显示名称" />
          </div>
          <div class="form-group">
            <textarea class="textarea" v-model="anatomyStore.operatorForm.description" placeholder="描述" rows="3"></textarea>
          </div>
          <div class="modal-actions">
            <button class="btn" @click="anatomyStore.closeOperatorEditor()">取消</button>
            <button class="btn btn-primary" @click="anatomyStore.saveOperator()">保存</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Category Manager Modal -->
    <Teleport to="body">
      <div v-if="anatomyStore.showCategoryManager" class="modal-backdrop" @click="anatomyStore.showCategoryManager = false">
        <div class="modal" @click.stop>
          <h3>分类管理</h3>
          <div class="form-group">
            <input type="text" class="input" v-model="anatomyStore.categoryForm.name" placeholder="分类标识" />
          </div>
          <div class="form-group">
            <input type="text" class="input" v-model="anatomyStore.categoryForm.display_name" placeholder="显示名称" />
          </div>
          <div class="modal-actions">
            <button class="btn" @click="anatomyStore.showCategoryManager = false">关闭</button>
            <button class="btn btn-primary" @click="anatomyStore.saveCategory()">保存</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Model Detail Modal -->
    <Teleport to="body">
      <div v-if="anatomyStore.showModelDetail" class="modal-backdrop" @click="anatomyStore.closeModelDetail()">
        <div class="modal modal-lg" @click.stop>
          <div class="modal-header">
            <h3>{{ anatomyStore.selectedModel?.display_name }}</h3>
            <button class="btn btn-sm" @click="anatomyStore.openEditModel()">编辑</button>
            <button class="btn btn-sm btn-ghost" @click="anatomyStore.closeModelDetail()">&times;</button>
          </div>
          <div class="modal-body">
            <p><strong>名称：</strong>{{ anatomyStore.selectedModel?.name }}</p>
            <p><strong>分类：</strong>{{ anatomyStore.selectedModel?.category }}</p>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Model Editor Modal -->
    <Teleport to="body">
      <div v-if="anatomyStore.showModelEditor" class="modal-backdrop" @click="anatomyStore.closeModelEditor()">
        <div class="modal modal-xl" @click.stop>
          <h3>{{ anatomyStore.modelEditorMode === 'create' ? '新建模型' : '编辑模型' }}</h3>
          <div class="form-group">
            <input type="text" class="input" v-model="anatomyStore.modelForm.name" placeholder="模型名称" />
          </div>
          <div class="form-group">
            <input type="text" class="input" v-model="anatomyStore.modelForm.display_name" placeholder="显示名称" />
          </div>
          <div class="modal-actions">
            <button class="btn" @click="anatomyStore.closeModelEditor()">取消</button>
            <button class="btn btn-primary" @click="anatomyStore.saveModel()">保存</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
