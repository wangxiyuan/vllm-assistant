import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { useAppStore } from './app'
import type { AnatomyBlock, ModelAssembly } from '@/utils/types'

// 重构后的 anatomy store：算子(building_block) + 组装(model_assembly)，
// YAML 为唯一数据源。支持算子构建（编辑/组合/循环）与组装预览。

export interface BlockNode {
  // 画布/编辑树上的一个算子实例节点
  id: string
  blockName: string          // 对应 building_block.name
  kind?: string              // atomic / composite（由 block 决定）
  params: Record<string, any>
  label?: string
  loop?: any                 // 循环配置
  condition?: string
  children: BlockNode[]      // composite 内层
  layerIdx?: number
}

export const useAnatomyStore = defineStore('anatomy', () => {
  const appStore = useAppStore()

  // ---- Blocks（算子库）----
  const blocks = ref<AnatomyBlock[]>([])
  const blocksLoading = ref(false)
  const blockSearch = ref('')
  const blockCategoryFilter = ref('')
  const blockKindFilter = ref<'all' | 'atomic' | 'composite'>('all')

  // ---- Assemblies（模型组装）----
  const assemblies = ref<ModelAssembly[]>([])
  const assembliesLoading = ref(false)
  const assemblySearch = ref('')
  const assemblyCategoryFilter = ref('')

  const assemblyCategories = computed(() => {
    const m = new Map<string, number>()
    for (const a of assemblies.value) m.set(a.category, (m.get(a.category) || 0) + 1)
    return [...m.entries()].map(([name, count]) => ({ name, count }))
  })

  const filteredAssemblies = computed(() => {
    let list = assemblies.value
    if (assemblyCategoryFilter.value) list = list.filter(a => a.category === assemblyCategoryFilter.value)
    if (assemblySearch.value) {
      const q = assemblySearch.value.toLowerCase()
      list = list.filter(a => a.name.toLowerCase().includes(q) || (a.description || '').toLowerCase().includes(q))
    }
    return list
  })

  // ---- 编辑状态 ----
  const showBlockDetail = ref(false)
  const selectedBlock = ref<AnatomyBlock | null>(null)
  const showBlockEditor = ref(false)
  const blockEditorMode = ref<'create' | 'edit'>('create')
  const blockForm = ref<any>({})
  const showAssemblyEditor = ref(false)
  const selectedAssembly = ref<ModelAssembly | null>(null)
  const showAssemblyDetail = ref(false)
  const assemblyForm = ref<any>({})

  // ---- YAML 导入状态 ----
  const showYAMLImport = ref(false)
  const yamlText = ref('')
  const yamlImporting = ref(false)
  const yamlResult = ref<any>(null)

  const blockCategories = computed(() => {
    const m = new Map<string, number>()
    for (const b of blocks.value) m.set(b.category, (m.get(b.category) || 0) + 1)
    return [...m.entries()].map(([name, count]) => ({ name, count }))
  })

  const filteredBlocks = computed(() => {
    let list = blocks.value
    if (blockCategoryFilter.value) list = list.filter(b => b.category === blockCategoryFilter.value)
    if (blockKindFilter.value !== 'all') list = list.filter(b => b.kind === blockKindFilter.value)
    if (blockSearch.value) {
      const q = blockSearch.value.toLowerCase()
      list = list.filter(b => b.name.toLowerCase().includes(q) || (b.description || '').toLowerCase().includes(q))
    }
    return list
  })

  function blockByName(name: string): AnatomyBlock | undefined {
    return blocks.value.find(b => b.name === name)
  }

  // ===== 加载 =====
  async function loadBlocks() {
    blocksLoading.value = true
    try {
      const data = await api('/api/anatomy/blocks')
      blocks.value = data.blocks || []
    } catch (e: any) {
      appStore.showToast('加载算子失败', e.message, 'error')
    } finally {
      blocksLoading.value = false
    }
  }

  async function loadAssemblies() {
    assembliesLoading.value = true
    try {
      const data = await api('/api/anatomy/assemblies')
      assemblies.value = data.assemblies || []
    } catch (e: any) {
      appStore.showToast('加载模型失败', e.message, 'error')
    } finally {
      assembliesLoading.value = false
    }
  }

  async function refresh() {
    await Promise.all([loadBlocks(), loadAssemblies()])
  }

  // ===== 算子 CRUD =====
  function openBlockDetail(block: AnatomyBlock) {
    selectedBlock.value = block
    showBlockDetail.value = true
  }
  function closeBlockDetail() {
    showBlockDetail.value = false
    selectedBlock.value = null
  }
  function openNewBlock(kind = 'atomic') {
    blockEditorMode.value = 'create'
    blockForm.value = {
      name: '', kind, category: 'other', description: '',
      formula: [],
      params_schema: { type: 'object', properties: {} },
      ports: { inputs: [], outputs: [] },
      children: [], file: '', weights: [], ops: [], edges: [], segments: [],
      forward_note: '', weight_prefix_note: '', note: '',
      state: [], tags: [], yaml: '', config: {},
    }
    showBlockEditor.value = true
  }
  function openEditBlock(block: AnatomyBlock) {
    blockEditorMode.value = 'edit'
    blockForm.value = {
      id: block.id, name: block.name, kind: block.kind, category: block.category,
      description: block.description || '',
      formula: [...(block.formula || [])],
      params_schema: JSON.parse(JSON.stringify(block.params_schema || {})),
      ports: JSON.parse(JSON.stringify(block.ports || { inputs: [], outputs: [] })),
      children: JSON.parse(JSON.stringify(block.children || [])),
      file: block.file || '',
      weights: JSON.parse(JSON.stringify(block.weights || [])),
      ops: JSON.parse(JSON.stringify(block.ops || [])),
      edges: JSON.parse(JSON.stringify(block.edges || [])),
      segments: JSON.parse(JSON.stringify(block.segments || [])),
      forward_note: block.forward_note || '',
      weight_prefix_note: block.weight_prefix_note || '',
      note: block.note || '',
      state: JSON.parse(JSON.stringify(block.state || [])),
      tags: [...(block.tags || [])], yaml: '',
      config: JSON.parse(JSON.stringify(block.config || {})),
    }
    showBlockEditor.value = true
  }
  function closeBlockEditor() {
    showBlockEditor.value = false
  }

  async function saveBlock() {
    if (!blockForm.value.name.trim()) {
      appStore.showToast(blockForm.value.kind === 'composite' ? '层名称不能为空' : '算子名称不能为空', '', 'error')
      return
    }
    if (!['atomic', 'composite'].includes(blockForm.value.kind)) {
      appStore.showToast('kind 必须是 atomic 或 composite', '', 'error')
      return
    }
    const body = {
      name: blockForm.value.name, kind: blockForm.value.kind, category: blockForm.value.category,
      description: blockForm.value.description, formula: blockForm.value.formula,
      params_schema: blockForm.value.params_schema,
      ports: blockForm.value.ports, children: blockForm.value.children,
      file: blockForm.value.file, weights: blockForm.value.weights, ops: blockForm.value.ops,
      edges: blockForm.value.edges, segments: blockForm.value.segments,
      forward_note: blockForm.value.forward_note,
      weight_prefix_note: blockForm.value.weight_prefix_note, note: blockForm.value.note,
      state: blockForm.value.state, tags: blockForm.value.tags, yaml: blockForm.value.yaml,
      config: blockForm.value.config,
    }
    const nn = blockForm.value.kind === 'composite' ? '层' : '算子'
    try {
      if (blockEditorMode.value === 'create') {
        await api('/api/anatomy/blocks', { method: 'POST', body: JSON.stringify(body) })
      } else {
        await api(`/api/anatomy/blocks/${blockForm.value.id}`, { method: 'PUT', body: JSON.stringify(body) })
      }
      appStore.showToast(`${nn}已保存`, '', 'success')
      showBlockEditor.value = false
      await loadBlocks()
    } catch (e: any) {
      appStore.showToast('保存失败', e.message, 'error')
    }
  }

  async function deleteBlock(block: AnatomyBlock) {
    const nn = block.kind === 'composite' ? '层' : '算子'
    const { confirmed } = await appStore.showConfirm({
      title: `删除${nn}`,
      message: `确定删除${nn}「${block.name}」？删除后不可恢复。`,
      confirmText: '删除',
      danger: true,
    })
    if (!confirmed) return
    try {
      await api(`/api/anatomy/blocks/${block.id}`, { method: 'DELETE' })
      appStore.showToast(`${nn}已删除`, '', 'success')
      closeBlockDetail()
      await loadBlocks()
    } catch (e: any) {
      appStore.showToast('删除失败', e.message, 'error')
    }
  }

  // ===== 组装 CRUD =====
  function openNewAssembly() {
    assemblyForm.value = {
      name: '', category: 'other', description: '',
      definition: { steps: [], edges: [], ports: { inputs: [], outputs: [] } },
      config: {}, file: '', forward_note: '', weight_prefix_note: '', note: '',
      formula: [],
      tags: [],
    }
    showAssemblyEditor.value = true
    showAssemblyDetail.value = false
  }
  function viewAssembly(asm: ModelAssembly) {
    showAssemblyDetail.value = true
    selectedAssembly.value = asm
    showAssemblyEditor.value = false
  }
  function closeAssemblyDetail() {
    showAssemblyDetail.value = false
    selectedAssembly.value = null
  }
  function openEditAssembly(asm: ModelAssembly) {
    const raw = asm.definition || { steps: [], edges: [], ports: {} }
    const def = JSON.parse(JSON.stringify(raw))
    assemblyForm.value = {
      id: asm.id, name: asm.name, category: asm.category, description: asm.description || '',
      definition: def,
      config: JSON.parse(JSON.stringify(asm.config || {})),
      file: raw.file || (asm as any).file || '',
      forward_note: raw.forward_note || (asm as any).forward_note || '',
      weight_prefix_note: raw.weight_prefix_note || (asm as any).weight_prefix_note || '',
      note: raw.note || (asm as any).note || '',
      formula: raw.formula || (asm as any).formula || [],
      tags: [...(asm.tags || [])],
    }
    showAssemblyEditor.value = true
    showAssemblyDetail.value = false
  }
  function closeAssemblyEditor() {
    showAssemblyEditor.value = false
  }

  async function saveViaYaml(yamlText: string): Promise<{ ok: boolean; error?: string }> {
    if (!yamlText.trim()) {
      appStore.showToast('YAML 内容为空', '', 'error')
      return { ok: false }
    }
    try {
      const res = await api('/api/anatomy/apply-yaml', { method: 'POST', body: JSON.stringify({ yaml: yamlText }) })
      appStore.showToast('已保存', '', 'success')
      await refresh()
      return { ok: true }
    } catch (e: any) {
      appStore.showToast('保存失败', e.message, 'error')
      return { ok: false, error: e.message }
    }
  }

  async function fetchBlockYaml(id: number): Promise<string> {
    try {
      const res = await api(`/api/anatomy/blocks/${id}/yaml`)
      return res.yaml || ''
    } catch (e: any) {
      appStore.showToast('获取 YAML 失败', e.message, 'error')
      return ''
    }
  }

  async function fetchAssemblyYaml(id: number): Promise<string> {
    try {
      const res = await api(`/api/anatomy/assemblies/${id}/yaml`)
      return res.yaml || ''
    } catch (e: any) {
      appStore.showToast('获取 YAML 失败', e.message, 'error')
      return ''
    }
  }

  async function fetchYamlTemplate(kind: string): Promise<string> {
    try {
      const res = await api(`/api/anatomy/yaml/template?kind=${encodeURIComponent(kind)}`)
      return res.yaml || ''
    } catch (e: any) {
      appStore.showToast('获取模板失败', e.message, 'error')
      return ''
    }
  }

  async function saveAssembly() {
    if (!assemblyForm.value.name.trim()) {
      appStore.showToast('模型名称不能为空', '', 'error')
      return
    }
    // 把 file/formula/notes 存入 definition（definition 为自由 JSON，随定义持久化）
    const def = { ...JSON.parse(JSON.stringify(assemblyForm.value.definition || {})), }
    def.file = assemblyForm.value.file || undefined
    def.formula = assemblyForm.value.formula || undefined
    def.forward_note = assemblyForm.value.forward_note || undefined
    def.weight_prefix_note = assemblyForm.value.weight_prefix_note || undefined
    def.note = assemblyForm.value.note || undefined
    const body = {
      name: assemblyForm.value.name, category: assemblyForm.value.category,
      description: assemblyForm.value.description,
      definition: def, config: assemblyForm.value.config,
      tags: assemblyForm.value.tags,
    }
    try {
      if (assemblyForm.value.id) {
        await api(`/api/anatomy/assemblies/${assemblyForm.value.id}`, { method: 'PUT', body: JSON.stringify(body) })
      } else {
        await api('/api/anatomy/assemblies', { method: 'POST', body: JSON.stringify(body) })
      }
      appStore.showToast('模型已保存', '', 'success')
      showAssemblyEditor.value = false
      await loadAssemblies()
    } catch (e: any) {
      appStore.showToast('保存失败', e.message, 'error')
    }
  }

  async function deleteAssembly(asm: ModelAssembly) {
    const { confirmed } = await appStore.showConfirm({
      title: '删除模型',
      message: `确定删除模型「${asm.name}」？删除后不可恢复。`,
      confirmText: '删除',
      danger: true,
    })
    if (!confirmed) return
    try {
      await api(`/api/anatomy/assemblies/${asm.id}`, { method: 'DELETE' })
      appStore.showToast('模型已删除', '', 'success')
      if (selectedAssembly.value?.id === asm.id) closeAssemblyDetail()
      await loadAssemblies()
    } catch (e: any) {
      appStore.showToast('删除失败', e.message, 'error')
    }
  }

  // ===== YAML 导入 =====
  function openYAMLImport() {
    yamlText.value = ''
    yamlResult.value = null
    showYAMLImport.value = true
  }
  function closeYAMLImport() {
    showYAMLImport.value = false
    yamlResult.value = null
  }
  async function doImport() {
    if (!yamlText.value.trim()) {
      appStore.showToast('请输入 YAML 内容', '', 'error')
      return
    }
    yamlImporting.value = true
    yamlResult.value = null
    try {
      const res = await api('/api/anatomy/import', { method: 'POST', body: JSON.stringify({ yaml: yamlText.value }) })
      yamlResult.value = res
      appStore.showToast(`导入完成：算子 ${res.imported_blocks || 0} 个，模型 ${res.imported_assemblies || 0} 个`, '', 'success')
      await refresh()
    } catch (e: any) {
      appStore.showToast('导入失败', e.message, 'error')
    } finally {
      yamlImporting.value = false
    }
  }

  async function validateAll() {
    try {
      const res = await api('/api/anatomy/validate')
      const errs = (res.errors || []).length
      const warns = (res.warnings || []).length
      appStore.showToast(`校验完成：${errs} 错误，${warns} 警告`, '', 'success')
      return res
    } catch (e: any) {
      appStore.showToast('校验失败', e.message, 'error')
      return null
    }
  }

  async function exportYAML(): Promise<string> {
    try {
      const res = await api('/api/anatomy/export')
      return res.yaml || ''
    } catch (e: any) {
      appStore.showToast('导出失败', e.message, 'error')
      return ''
    }
  }

  // ===== 组装编辑器（画布数据操作）=====
  function addStep() {
    const def = assemblyForm.value.definition
    if (!def.steps) def.steps = []
    def.steps.push({
      id: `step${Date.now()}`, block: '', as: '', port_bind: {},
      params: {}, label: '',
    })
  }
  function removeStep(idx: number) {
    const def = assemblyForm.value.definition
    if (!def?.steps) return
    appStore.showConfirm({
      title: '删除步骤',
      message: '确定删除此步骤？',
      confirmText: '删除',
      danger: true,
    }).then(({ confirmed }) => {
      if (confirmed) def.steps.splice(idx, 1)
    })
  }
  function moveStepUp(idx: number) {
    const steps = assemblyForm.value.definition.steps
    if (!steps || idx <= 0) return
    const tmp = steps[idx - 1]
    steps[idx - 1] = steps[idx]
    steps[idx] = tmp
  }
  function moveStepDown(idx: number) {
    const steps = assemblyForm.value.definition.steps
    if (!steps || idx >= steps.length - 1) return
    const tmp = steps[idx + 1]
    steps[idx + 1] = steps[idx]
    steps[idx] = tmp
  }
  function onStepBlockChange(step: any) {
    const blk = blockByName(step.block)
    if (blk) {
      step.port_bind = {}
      if (blk.params_schema?.properties) {
        const defaults: Record<string, any> = {}
        for (const [k, p] of Object.entries(blk.params_schema.properties as Record<string, any>)) {
          if (p.default !== undefined) defaults[k] = p.default
        }
        step.port_bind = defaults
      }
    }
  }

  return {
    blocks, blocksLoading, blockSearch, blockCategoryFilter, blockKindFilter,
    assemblies, assembliesLoading, assemblySearch, assemblyCategoryFilter,
    assemblyCategories, filteredAssemblies,
    showBlockDetail, selectedBlock, showBlockEditor, blockEditorMode, blockForm,
    showAssemblyEditor, selectedAssembly, showAssemblyDetail,
    assemblyForm, showYAMLImport, yamlText, yamlImporting, yamlResult,
    blockCategories, filteredBlocks, blockByName,
    loadBlocks, loadAssemblies, refresh,
    openBlockDetail, closeBlockDetail, openNewBlock, openEditBlock, closeBlockEditor, saveBlock, deleteBlock,
    openNewAssembly, viewAssembly, closeAssemblyDetail, openEditAssembly, closeAssemblyEditor, saveAssembly, deleteAssembly,
    saveViaYaml, fetchBlockYaml, fetchAssemblyYaml, fetchYamlTemplate,
    openYAMLImport, closeYAMLImport, doImport, validateAll, exportYAML,
    addStep, removeStep, moveStepUp, moveStepDown, onStepBlockChange,
  }
})