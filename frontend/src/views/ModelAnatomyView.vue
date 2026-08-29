<script setup lang="ts">
/**
 * ModelAnatomyView.vue —— 模型拆解（算子式，YAML 为唯一数据源）
 *
 * Tab「算子」：原子算子库（左）+ 分类/搜索 + 新建/编辑/详情。
 * Tab「层」：组合算子（layer，composite）库（左）+ 分类/搜索 + 新建/编辑/详情。
 * Tab「模型」：组装列表（左）+ 详情/新建/编辑（右）+ YAML 导入/导出/校验。
 */
import { onMounted, ref, computed } from 'vue'
import ChatDrawer from '@/components/ai/ChatDrawer.vue'
import { useAnatomyStore } from '@/stores/anatomy'
import BlockLibrary from '@/components/anatomy/BlockLibrary.vue'
import BlockInspector from '@/components/anatomy/BlockInspector.vue'
import BlockDetail from '@/components/anatomy/BlockDetail.vue'
import BlockEditor from '@/components/anatomy/BlockEditor.vue'
import AssemblyDiagram from '@/components/anatomy/AssemblyDiagram.vue'
import AssemblyGraph from '@/components/anatomy/AssemblyGraph.vue'
import AssemblyEditor from '@/components/anatomy/AssemblyEditor.vue'
import YAMLImportModal from '@/components/anatomy/YAMLImportModal.vue'

const store = useAnatomyStore()
const tab = ref<'ops' | 'layers' | 'assemblies'>('ops')
const asmViewMode = ref<'graph' | 'tree'>('graph')

onMounted(() => {
  store.loadBlocks()
  store.loadAssemblies()
})

const opsCount = computed(() => store.blocks.filter(b => b.kind !== 'composite').length)
const layersCount = computed(() => store.blocks.filter(b => b.kind === 'composite').length)

function openAssemblyDetail(a: any) {
  store.viewAssembly(a)
}

function selectBlock(b: any) {
  store.selectedBlock = b
  store.showBlockDetail = false
}

function switchBlockTab(kind: 'ops' | 'layers') {
  tab.value = kind
  store.blockCategoryFilter = ''
  store.blockSearch = ''
}

function switchAssemblyTab() {
  tab.value = 'assemblies'
  store.assemblyCategoryFilter = ''
  store.assemblySearch = ''
}

async function doExport() {
  const text = await store.exportYAML()
  if (!text) return
  const blob = new Blob([text], { type: 'text/yaml;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'anatomy_export.yaml'
  link.click()
  URL.revokeObjectURL(url)
}

async function doValidate() {
  await store.validateAll()
}

// ── AI 助手抽屉（AI 帮我建）──
const aiChatOpen = ref(false)
const aiChatIntent = ref('')
function openAIChat(intent: string) {
  aiChatIntent.value = intent
  aiChatOpen.value = true
}
</script>

<template>
  <div class="view-container">
    <div class="view-header">
      <h2 class="view-title">模型拆解</h2>
      <div class="view-header-actions">
        <button class="btn btn-sm" @click="doValidate()">校验</button>
        <button class="btn btn-sm" @click="doExport()">导出 YAML</button>
        <button class="btn btn-sm" @click="openAIChat('anatomy')">✨ AI 拆解</button>
        <button class="btn btn-primary btn-sm" @click="store.openYAMLImport()">导入 YAML</button>
      </div>
    </div>

    <div class="tab-bar" style="margin-bottom:var(--space-5)">
      <button class="tab" :class="{ active: tab === 'ops' }" @click="switchBlockTab('ops')">
        算子 <span class="badge">{{ opsCount }}</span>
      </button>
      <button class="tab" :class="{ active: tab === 'layers' }" @click="switchBlockTab('layers')">
        层 <span class="badge">{{ layersCount }}</span>
      </button>
      <button class="tab" :class="{ active: tab === 'assemblies' }" @click="switchAssemblyTab()">
        模型 <span class="badge">{{ store.assemblies.length }}</span>
      </button>
    </div>

    <!-- ========== 算子 Tab（原子）========== -->
    <div v-if="tab === 'ops'" class="blocks-layout">
      <div class="blocks-lib-panel">
        <BlockLibrary
          :blocks="store.blocks"
          :search="store.blockSearch"
          :categoryFilter="store.blockCategoryFilter"
          :kindFilter="store.blockKindFilter"
          fixed-kind="atomic"
          label="算子"
          @update:search="store.blockSearch = $event"
          @update:categoryFilter="store.blockCategoryFilter = $event"
          @update:kindFilter="store.blockKindFilter = $event"
          @openDetail="selectBlock($event)"
          @newBlock="store.openNewBlock('atomic')"
        />
      </div>
      <div class="blocks-detail-panel panel">
        <div class="panel-header" v-if="store.selectedBlock">
          <div class="panel-title">算子详情</div>
        </div>
        <div class="panel-body" style="padding:0;">
          <BlockInspector v-if="store.selectedBlock" :block="store.selectedBlock" :blocks="store.blocks"
            @edit="store.openEditBlock(store.selectedBlock!)" @del="store.deleteBlock(store.selectedBlock!)" />
          <div v-else class="block-detail-empty">
            <div class="block-detail-empty-title">选择算子查看详情</div>
            <div class="block-detail-empty-sub">从左侧算子库点击一个原子算子，这里会展示它的端口、参数与 vLLM 引用。</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== 层 Tab（composite）========== -->
    <div v-if="tab === 'layers'" class="blocks-layout">
      <div class="blocks-lib-panel">
        <BlockLibrary
          :blocks="store.blocks"
          :search="store.blockSearch"
          :categoryFilter="store.blockCategoryFilter"
          :kindFilter="store.blockKindFilter"
          fixed-kind="composite"
          label="层"
          @update:search="store.blockSearch = $event"
          @update:categoryFilter="store.blockCategoryFilter = $event"
          @update:kindFilter="store.blockKindFilter = $event"
          @openDetail="selectBlock($event)"
          @newBlock="store.openNewBlock('composite')"
        />
      </div>
      <div class="blocks-detail-panel panel">
        <div class="panel-header" v-if="store.selectedBlock">
          <div class="panel-title">层详情</div>
        </div>
        <div class="panel-body" style="padding:0;">
          <BlockInspector v-if="store.selectedBlock" :block="store.selectedBlock" :blocks="store.blocks"
            @edit="store.openEditBlock(store.selectedBlock!)" @del="store.deleteBlock(store.selectedBlock!)" />
          <div v-else class="block-detail-empty">
            <div class="block-detail-empty-title">选择层查看详情</div>
            <div class="block-detail-empty-sub">从左侧层库点击一个组合层，这里会展示它的子算子、端口、参数与 vLLM 引用。</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== 模型 Tab ========== -->
    <div v-if="tab === 'assemblies'" class="assemblies-layout">
      <div class="asm-list-panel">
          <div class="asm-pane-header">
            <input class="input input-sm w-100" v-model="store.assemblySearch" placeholder="搜索模型…" />
            <button class="btn btn-primary btn-xs w-100 mt-1" @click="store.openNewAssembly()">+ 新建模型</button>
          </div>
          <div class="asm-cats">
            <button class="asm-cat-chip" :class="{ active: !store.assemblyCategoryFilter }" @click="store.assemblyCategoryFilter = ''">全部</button>
            <button v-for="c in store.assemblyCategories" :key="c.name" class="asm-cat-chip"
              :class="{ active: store.assemblyCategoryFilter === c.name }" @click="store.assemblyCategoryFilter = c.name">
              {{ c.name }}<span class="asm-cat-count">{{ c.count }}</span>
            </button>
          </div>
          <div class="asm-group-list">
            <div v-if="store.assembliesLoading" class="empty-state"><div class="empty-title">加载中…</div></div>
            <div v-else-if="store.filteredAssemblies.length === 0" class="empty-state">
              <div class="empty-title">暂无模型</div>
              <div class="empty-desc">通过「导入 YAML」或「新建模型」搭建</div>
            </div>
            <div v-else class="asm-list">
              <div v-for="a in store.filteredAssemblies" :key="a.id" class="asm-card"
                   :class="{ selected: store.selectedAssembly?.id === a.id }"
                   @click="openAssemblyDetail(a)">
                <div class="asm-card-body">
                  <div class="asm-card-title">
                    <span class="asm-name">{{ a.name }}</span>
                  </div>
                  <div class="asm-card-steps">
                    {{ (a.definition?.steps || []).length }} 步 · {{ a.category }}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

      <div class="asm-detail-panel">
        <!-- Detail -->
        <div v-if="store.showAssemblyDetail && store.selectedAssembly" class="panel">
          <div class="panel-header">
            <div class="panel-title">
              <span>{{ store.selectedAssembly.name }}</span>
              <span class="badge ml-1">{{ store.selectedAssembly.category }}</span>
            </div>
            <div class="panel-actions">
              <button class="btn btn-sm" @click="store.openEditAssembly(store.selectedAssembly)">编辑</button>
              <button class="btn btn-sm btn-danger" @click="store.deleteAssembly(store.selectedAssembly)">删除</button>
              <button class="btn btn-sm" @click="store.closeAssemblyDetail()">关闭</button>
            </div>
          </div>
          <div class="panel-body">
            <p v-if="store.selectedAssembly.description" class="asm-desc">{{ store.selectedAssembly.description }}</p>
            <div class="asm-view-toggle">
              <button class="btn btn-xs" :class="{ active: asmViewMode === 'graph' }" @click="asmViewMode = 'graph'">图</button>
              <button class="btn btn-xs" :class="{ active: asmViewMode === 'tree' }" @click="asmViewMode = 'tree'">树</button>
            </div>
            <div class="asm-diagram-wrap">
              <AssemblyGraph v-if="asmViewMode === 'graph' && store.selectedAssembly.definition"
                :definition="store.selectedAssembly.definition"
                :config="store.selectedAssembly.config"
                :blocks="store.blocks" :assemblies="store.assemblies" :is-assembly="true" />
              <AssemblyDiagram v-else :definition="store.selectedAssembly.definition" :config="store.selectedAssembly.config" :blocks="store.blocks" :assemblies="store.assemblies" />
            </div>
          </div>
        </div>

        <!-- Empty -->
        <div v-else class="panel">
          <div class="panel-body">
            <div class="block-detail-empty">从左侧选择模型查看，或新建/导入模型。</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== Block Detail Modal ========== -->
    <BlockDetail v-if="store.showBlockDetail && store.selectedBlock"
      :block="store.selectedBlock"
      @close="store.closeBlockDetail()"
      @edit="store.openEditBlock(store.selectedBlock!)"
      @del="store.deleteBlock(store.selectedBlock!)" />

    <!-- ========== Block Editor Modal ========== -->
    <BlockEditor v-if="store.showBlockEditor"
      :form="store.blockForm"
      :mode="store.blockEditorMode"
      @close="store.closeBlockEditor()"
      @saved="store.closeBlockEditor()" />

    <!-- ========== Assembly Editor Modal ========== -->
    <AssemblyEditor v-if="store.showAssemblyEditor"
      :form="store.assemblyForm"
      :blocks="store.blocks"
      @close="store.closeAssemblyEditor()"
      @saved="store.closeAssemblyEditor()" />

    <!-- ========== YAML Import Modal ========== -->
    <YAMLImportModal
      :open="store.showYAMLImport"
      :yamlText="store.yamlText"
      :importing="store.yamlImporting"
      :result="store.yamlResult"
      @update:yamlText="store.yamlText = $event"
      @close="store.closeYAMLImport()"
      @doImport="store.doImport()" />
    <ChatDrawer :open="aiChatOpen" :intent="aiChatIntent" @close="aiChatOpen = false" />
  </div>
</template>

<style scoped>
.view-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--space-5); }
.view-header-actions { display: flex; gap: var(--space-2); }

.blocks-layout, .assemblies-layout { display: grid; grid-template-columns: 300px 1fr; gap: var(--space-4); height: calc(100vh - 220px); min-height: 480px; align-items: stretch; }
.blocks-lib-panel, .asm-list-panel { border: 1px solid var(--border-faint); border-radius: var(--radius-md); padding: var(--space-4); background: var(--bg-elev-1); display: flex; flex-direction: column; min-height: 0; }
.blocks-detail-panel, .asm-detail-panel { min-height: 0; overflow: auto; }
.block-detail-empty { color: var(--text-tertiary); text-align: center; padding: 40px; font-size: var(--text-sm); }

.asm-list { display: flex; flex-direction: column; gap: var(--space-2); }
.asm-pane-header {} 
.asm-cats { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 10px; }
.asm-cat-chip { background: var(--bg-elev-2); border: 1px solid var(--border-faint); color: var(--text-secondary); font-size: 15px; padding: 2px 8px; border-radius: 12px; cursor: pointer; }
.asm-cat-chip.active { background: var(--amber-glow-soft); border-color: var(--amber-dim); color: var(--amber); }
.asm-cat-count { margin-left: 4px; opacity: 0.6; font-size: 15px; }
.asm-group-list { flex: 1; overflow: auto; margin-top: 10px; }
.asm-card { padding: var(--space-3); background: var(--bg-elev-2); border: 1px solid var(--border-faint); border-radius: var(--radius-sm); cursor: pointer; }
.asm-card:hover { border-color: var(--amber-dim); }
.asm-card.selected { border-color: var(--amber); background: var(--amber-glow-soft); }
.asm-card-title { display: flex; align-items: center; gap: var(--space-2); }
.asm-name { font-family: var(--font-mono); font-size: 15px; font-weight: 600; color: var(--text-primary); }
.asm-card-steps { font-size: 15px; color: var(--text-tertiary); margin-top: var(--space-1); }
.asm-desc { color: var(--text-secondary); font-size: var(--text-sm); margin-bottom: var(--space-4); }
.asm-diagram-wrap { border: 1px solid var(--border-faint); border-radius: var(--radius-md); background: var(--bg-base); }
.asm-view-toggle { display: flex; gap: 4px; margin-bottom: var(--space-2); }
.asm-view-toggle .btn.active { background: var(--amber-glow-soft); border-color: var(--amber-dim); color: var(--amber); }
</style>