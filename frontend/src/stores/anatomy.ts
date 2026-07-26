import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { useAppStore } from './app'
import type { Operator, Model } from '@/utils/types'

export const useAnatomyStore = defineStore('anatomy', () => {
  const anatomyTab = ref<'operators' | 'models'>('operators')

  // Operators
  const operators = ref<Operator[]>([])
  const operatorsLoading = ref(false)
  const operatorFilterCategory = ref('')
  const operatorSearch = ref('')
  const showOperatorDetail = ref(false)
  const selectedOperator = ref<Operator | null>(null)
  const showOperatorEditor = ref(false)
  const operatorEditorMode = ref<'create' | 'edit'>('create')
  const operatorForm = ref({
    id: null as number | null, name: '', display_name: '', description: '',
    category: 'other', params_schema: '{}', input_shape_desc: '', output_shape_desc: '',
    vllm_code_refs: '[]', tags: [] as string[], user_id: null as number | null,
  })
  const operatorTagInput = ref('')
  const operatorParamsSchemaValid = ref(true)
  const operatorParamsSchemaError = ref('')

  // Categories
  const operatorCategoryOptions = ref<any[]>([])
  const showCategoryManager = ref(false)
  const categoryManagerLoading = ref(false)
  const categoryList = ref<any[]>([])
  const editingCategory = ref<any>(null)
  const categoryForm = ref({ name: '', display_name: '', description: '', sort_order: 0 })
  const categoryFormMode = ref<'create' | 'edit'>('create')

  // Models
  const models = ref<Model[]>([])
  const modelsLoading = ref(false)
  const modelSearch = ref('')
  const modelFilterCategory = ref('')
  const selectedModel = ref<Model | null>(null)
  const showModelDetail = ref(false)
  const modelDetailLoading = ref(false)
  const showModelEditor = ref(false)
  const modelEditorMode = ref<'create' | 'edit'>('create')
  const modelForm = ref({
    id: null as number | null, name: '', display_name: '', description: '',
    category: 'other', architecture: [] as any[], params_summary: '',
    tags: [] as string[], user_id: null as number | null,
  })
  const editingArchitecture = ref<any[]>([])
  const modelTagInput = ref('')
  const modelFormSnapshot = ref<any>(null)

  const modelCategoryOptions = [
    { value: 'dense', label: 'Dense' },
    { value: 'moe', label: 'MoE' },
    { value: 'hybrid', label: 'Hybrid' },
    { value: 'state_space', label: 'State Space' },
    { value: 'other', label: 'Other' },
  ]

  const _categoryColors = [
    'var(--signal-blue)', 'var(--signal-green)', 'var(--signal-purple)',
    'var(--signal-cyan)', 'var(--amber)', 'var(--signal-red)', 'var(--signal-yellow)', 'var(--text-tertiary)',
  ]

  // Operator actions
  async function loadOperators() {
    operatorsLoading.value = true
    try {
      const params = new URLSearchParams()
      if (operatorFilterCategory.value) params.set('category', operatorFilterCategory.value)
      if (operatorSearch.value) params.set('search', operatorSearch.value)
      const qs = params.toString()
      const data: any = await api(`/api/anatomy/operators${qs ? '?' + qs : ''}`)
      operators.value = data.operators || []
    } catch (e: any) {
      useAppStore().showToast('加载算子失败', e.message, 'error')
    } finally {
      operatorsLoading.value = false
    }
  }

  function operatorById(id: number): Operator | undefined {
    return operators.value.find(o => o.id === id)
  }

  function viewOperatorDetail(op: Operator) {
    selectedOperator.value = op
    showOperatorDetail.value = true
  }

  function closeOperatorDetail() {
    showOperatorDetail.value = false
    selectedOperator.value = null
  }

  function editFromDetail() {
    if (!selectedOperator.value) return
    const op = selectedOperator.value
    closeOperatorDetail()
    setTimeout(() => openEditOperator(op), 50)
  }

  function openNewOperator() {
    operatorEditorMode.value = 'create'
    operatorForm.value = {
      id: null, name: '', display_name: '', description: '',
      category: 'other', params_schema: '{}', input_shape_desc: '', output_shape_desc: '',
      vllm_code_refs: '[]', tags: [], user_id: null,
    }
    operatorTagInput.value = ''
    operatorParamsSchemaValid.value = true
    operatorParamsSchemaError.value = ''
    showOperatorEditor.value = true
  }

  function openEditOperator(op: Operator) {
    operatorEditorMode.value = 'edit'
    operatorForm.value = {
      id: op.id, name: op.name || '', display_name: op.display_name || '',
      description: op.description || '', category: op.category || 'other',
      params_schema: JSON.stringify(op.params_schema || {}, null, 2),
      input_shape_desc: op.input_shape_desc || '', output_shape_desc: op.output_shape_desc || '',
      vllm_code_refs: JSON.stringify(op.vllm_code_refs || [], null, 2),
      tags: [...(op.tags || [])], user_id: op.user_id || null,
    }
    operatorTagInput.value = ''
    operatorParamsSchemaValid.value = true
    operatorParamsSchemaError.value = ''
    showOperatorEditor.value = true
  }

  function closeOperatorEditor() {
    showOperatorEditor.value = false
  }

  function addOperatorTag() {
    const t = operatorTagInput.value.trim().toLowerCase()
    if (t && !operatorForm.value.tags.includes(t)) operatorForm.value.tags.push(t)
    operatorTagInput.value = ''
  }

  function removeOperatorTag(tag: string) {
    operatorForm.value.tags = operatorForm.value.tags.filter(t => t !== tag)
  }

  function validateParamsSchema(): any {
    try {
      const val = JSON.parse(operatorForm.value.params_schema)
      operatorParamsSchemaValid.value = true
      operatorParamsSchemaError.value = ''
      return val
    } catch (e: any) {
      operatorParamsSchemaValid.value = false
      operatorParamsSchemaError.value = e.message || 'Invalid JSON'
      return null
    }
  }

  async function saveOperator() {
    if (!operatorForm.value.name.trim()) {
      useAppStore().showToast('算子名称不能为空', '', 'error')
      return
    }
    if (!operatorForm.value.display_name.trim()) {
      useAppStore().showToast('显示名称不能为空', '', 'error')
      return
    }
    let parsedSchema = {}
    if (operatorForm.value.params_schema.trim()) {
      const result = validateParamsSchema()
      if (!result) return
      parsedSchema = result
    }
    let parsedRefs: any[] = []
    if (operatorForm.value.vllm_code_refs.trim()) {
      try {
        parsedRefs = JSON.parse(operatorForm.value.vllm_code_refs)
      } catch (e: any) {
        useAppStore().showToast('代码引用 JSON 格式错误', e.message, 'error')
        return
      }
    }
    const body = {
      name: operatorForm.value.name, display_name: operatorForm.value.display_name,
      description: operatorForm.value.description, category: operatorForm.value.category,
      params_schema: parsedSchema, input_shape_desc: operatorForm.value.input_shape_desc,
      output_shape_desc: operatorForm.value.output_shape_desc, vllm_code_refs: parsedRefs,
      tags: operatorForm.value.tags, user_id: operatorForm.value.user_id,
    }
    try {
      if (operatorEditorMode.value === 'create') {
        await api('/api/anatomy/operators', { method: 'POST', body: JSON.stringify(body) })
        useAppStore().showToast('算子已创建', '', 'success')
      } else {
        await api(`/api/anatomy/operators/${operatorForm.value.id}`, { method: 'PUT', body: JSON.stringify(body) })
        useAppStore().showToast('算子已更新', '', 'success')
      }
      showOperatorEditor.value = false
      await loadOperators()
    } catch (e: any) {
      useAppStore().showToast('保存失败', e.message, 'error')
    }
  }

  async function deleteOperator(op: Operator) {
    if (!confirm(`确定删除算子「${op.display_name}」？此操作不可撤销。`)) return
    try {
      await api(`/api/anatomy/operators/${op.id}`, { method: 'DELETE' })
      useAppStore().showToast('算子已删除', '', 'success')
      closeOperatorDetail()
      await loadOperators()
    } catch (e: any) {
      useAppStore().showToast('删除失败', e.message, 'error')
    }
  }

  // Category actions
  async function loadCategories() {
    try {
      const data: any = await api('/api/anatomy/operators/categories')
      const colors = _categoryColors
      operatorCategoryOptions.value = (data.categories || []).map((c: any, i: number) => ({
        value: c.name, label: c.display_name, color: colors[i % colors.length],
      }))
    } catch (_) {}
  }

  function openCategoryManager() {
    showCategoryManager.value = true
    categoryForm.value = { name: '', display_name: '', description: '', sort_order: 0 }
    categoryFormMode.value = 'create'
    loadCategoryList()
  }

  async function loadCategoryList() {
    categoryManagerLoading.value = true
    try {
      const data: any = await api('/api/anatomy/operators/categories')
      categoryList.value = data.categories || []
    } catch (_) {
      useAppStore().showToast('加载分类失败', '', 'error')
    } finally {
      categoryManagerLoading.value = false
    }
  }

  function openEditCategory(cat: any) {
    categoryFormMode.value = 'edit'
    categoryForm.value = { name: cat.name, display_name: cat.display_name, description: cat.description || '', sort_order: cat.sort_order || 0 }
    editingCategory.value = cat
  }

  async function saveCategory() {
    if (!categoryForm.value.name.trim() || !categoryForm.value.display_name.trim()) return
    try {
      if (categoryFormMode.value === 'create') {
        await api('/api/anatomy/operators/categories', { method: 'POST', body: JSON.stringify(categoryForm.value) })
      } else if (editingCategory.value) {
        await api(`/api/anatomy/operators/categories/${editingCategory.value.id}`, {
          method: 'PUT', body: JSON.stringify(categoryForm.value),
        })
      }
      await loadCategoryList()
      await loadCategories()
      categoryForm.value = { name: '', display_name: '', description: '', sort_order: 0 }
      categoryFormMode.value = 'create'
      editingCategory.value = null
    } catch (e: any) {
      useAppStore().showToast('保存分类失败', e.message, 'error')
    }
  }

  async function moveCategory(cat: any, direction: 'up' | 'down') {
    const newOrder = cat.sort_order + (direction === 'up' ? -1 : 1)
    try {
      await api(`/api/anatomy/operators/categories/${cat.id}`, {
        method: 'PUT', body: JSON.stringify({ sort_order: newOrder }),
      })
      await loadCategoryList()
      await loadCategories()
    } catch (e: any) {
      useAppStore().showToast('调整排序失败', e.message, 'error')
    }
  }

  async function deleteCategory(cat: any) {
    if (!confirm(`确定删除分类「${cat.display_name}」？`)) return
    try {
      await api(`/api/anatomy/operators/categories/${cat.id}`, { method: 'DELETE' })
      await loadCategoryList()
      await loadCategories()
    } catch (e: any) {
      useAppStore().showToast('删除分类失败', e.message, 'error')
    }
  }

  // Model actions
  async function loadModels() {
    modelsLoading.value = true
    try {
      const params = new URLSearchParams()
      if (modelSearch.value) params.set('search', modelSearch.value)
      if (modelFilterCategory.value) params.set('category', modelFilterCategory.value)
      const qs = params.toString()
      const data: any = await api(`/api/anatomy/models${qs ? '?' + qs : ''}`)
      models.value = data.models || []
    } catch (e: any) {
      useAppStore().showToast('加载模型失败', e.message, 'error')
    } finally {
      modelsLoading.value = false
    }
  }

  async function viewModel(model: Model) {
    modelDetailLoading.value = true
    showModelDetail.value = true
    selectedModel.value = null
    showModelEditor.value = false
    try {
      const data = await api(`/api/anatomy/models/${model.id}`)
      selectedModel.value = data
    } catch (e: any) {
      useAppStore().showToast('加载模型详情失败', e.message, 'error')
      showModelDetail.value = false
    } finally {
      modelDetailLoading.value = false
    }
  }

  function closeModelDetail() {
    showModelDetail.value = false
    selectedModel.value = null
  }

  function openNewModel() {
    modelEditorMode.value = 'create'
    modelForm.value = {
      id: null, name: '', display_name: '', description: '',
      category: 'other', architecture: [], params_summary: '', tags: [], user_id: null,
    }
    editingArchitecture.value = []
    modelTagInput.value = ''
    modelFormSnapshot.value = null
    showModelEditor.value = true
    showModelDetail.value = false
  }

  function openEditModel() {
    if (!selectedModel.value) return
    modelEditorMode.value = 'edit'
    const arch = selectedModel.value.architecture || []
    modelForm.value = {
      id: selectedModel.value.id, name: selectedModel.value.name || '',
      display_name: selectedModel.value.display_name || '',
      description: selectedModel.value.description || '',
      category: selectedModel.value.category || 'other',
      architecture: JSON.parse(JSON.stringify(arch)),
      params_summary: selectedModel.value.params_summary
        ? JSON.stringify(selectedModel.value.params_summary, null, 2) : '',
      tags: [...(selectedModel.value.tags || [])],
      user_id: selectedModel.value.user_id || null,
    }
    editingArchitecture.value = JSON.parse(JSON.stringify(arch))
    modelTagInput.value = ''
    _takeModelFormSnapshot()
    showModelEditor.value = true
    showModelDetail.value = false
  }

  function closeModelEditor() {
    showModelEditor.value = false
    modelFormSnapshot.value = null
  }

  function _takeModelFormSnapshot() {
    modelFormSnapshot.value = {
      name: modelForm.value.name, display_name: modelForm.value.display_name,
      description: modelForm.value.description, tags: [...modelForm.value.tags],
      architecture: JSON.parse(JSON.stringify(editingArchitecture.value)),
    }
  }

  function addModelTag() {
    const t = modelTagInput.value.trim().toLowerCase()
    if (t && !modelForm.value.tags.includes(t)) modelForm.value.tags.push(t)
    modelTagInput.value = ''
  }

  function removeModelTag(tag: string) {
    modelForm.value.tags = modelForm.value.tags.filter(t => t !== tag)
  }

  function addStage() {
    editingArchitecture.value.push({
      type: 'operator', operator_id: null, operator_name: '',
      params: {}, label: '', children: [], order: editingArchitecture.value.length,
    })
  }

  function addRepeatBlock() {
    editingArchitecture.value.push({
      type: 'repeat_block', label: '', repeat_count: 1,
      contents: [[]], order: editingArchitecture.value.length,
    })
  }

  function removeStage(index: number) {
    if (!confirm('确定删除这个阶段？')) return
    editingArchitecture.value.splice(index, 1)
    _reorderStages()
  }

  function addStageBefore(index: number) {
    editingArchitecture.value.splice(index, 0, {
      type: 'operator', operator_id: null, operator_name: '',
      params: {}, label: '', children: [], order: editingArchitecture.value.length,
    })
    _reorderStages()
  }

  function addRepeatBlockBefore(index: number) {
    editingArchitecture.value.splice(index, 0, {
      type: 'repeat_block', label: '', repeat_count: 1,
      contents: [[]], order: editingArchitecture.value.length,
    })
    _reorderStages()
  }

  function moveStageUp(index: number) {
    if (index <= 0) return
    const tmp = editingArchitecture.value[index]
    editingArchitecture.value[index] = editingArchitecture.value[index - 1]
    editingArchitecture.value[index - 1] = tmp
    _reorderStages()
  }

  function moveStageDown(index: number) {
    if (index >= editingArchitecture.value.length - 1) return
    const tmp = editingArchitecture.value[index]
    editingArchitecture.value[index] = editingArchitecture.value[index + 1]
    editingArchitecture.value[index + 1] = tmp
    _reorderStages()
  }

  function _reorderStages() {
    editingArchitecture.value.forEach((s: any, i: number) => { s.order = i })
  }

  function onStageOperatorChange(stage: any) {
    const op = operatorById(stage.operator_id)
    if (op) {
      stage.operator_name = op.name
      const schema = op.params_schema
      if (schema && schema.properties) {
        const defaults: Record<string, any> = {}
        for (const [key, prop] of Object.entries(schema.properties as Record<string, { default?: any }>)) {
          if ((prop as any).default !== undefined) defaults[key] = (prop as any).default
        }
        stage.params = defaults
      } else {
        stage.params = {}
      }
    } else {
      stage.operator_name = ''
      stage.params = {}
    }
  }

  function addRepeatBlockContent(repeatBlock: any) {
    repeatBlock.contents.push([])
  }

  function removeRepeatBlockContent(repeatBlock: any, contentIndex: number) {
    if (repeatBlock.contents.length <= 1) return
    if (!confirm('确定删除这套内容？')) return
    repeatBlock.contents.splice(contentIndex, 1)
  }

  function addStageToContent(repeatBlock: any, contentIndex: number) {
    repeatBlock.contents[contentIndex].push({
      type: 'operator', operator_id: null, operator_name: '',
      params: {}, label: '', children: [], order: repeatBlock.contents[contentIndex].length,
    })
  }

  function removeStageFromContent(repeatBlock: any, contentIndex: number, stageIndex: number) {
    if (!confirm('确定删除这个算子？')) return
    repeatBlock.contents[contentIndex].splice(stageIndex, 1)
  }

  async function saveModel() {
    if (!modelForm.value.name.trim()) {
      useAppStore().showToast('模型名称不能为空', '', 'error')
      return
    }
    if (!modelForm.value.display_name.trim()) {
      useAppStore().showToast('显示名称不能为空', '', 'error')
      return
    }
    if (editingArchitecture.value.length === 0) {
      useAppStore().showToast('请至少添加一个阶段', '', 'error')
      return
    }
    let parsedSummary = {}
    if (modelForm.value.params_summary?.trim()) {
      try {
        parsedSummary = JSON.parse(modelForm.value.params_summary)
      } catch (e: any) {
        useAppStore().showToast('参数汇总 JSON 格式错误', e.message, 'error')
        return
      }
    }
    const body = {
      name: modelForm.value.name, display_name: modelForm.value.display_name,
      description: modelForm.value.description, category: modelForm.value.category || 'other',
      architecture: editingArchitecture.value, params_summary: parsedSummary,
      tags: modelForm.value.tags, user_id: modelForm.value.user_id,
    }
    try {
      if (modelEditorMode.value === 'create') {
        await api('/api/anatomy/models', { method: 'POST', body: JSON.stringify(body) })
        useAppStore().showToast('模型已创建', '', 'success')
      } else {
        await api(`/api/anatomy/models/${modelForm.value.id}`, { method: 'PUT', body: JSON.stringify(body) })
        useAppStore().showToast('模型已更新', '', 'success')
      }
      showModelEditor.value = false
      modelFormSnapshot.value = null
      await loadModels()
      if (selectedModel.value && selectedModel.value.id === modelForm.value.id) {
        await viewModel(selectedModel.value)
      }
    } catch (e: any) {
      useAppStore().showToast('保存失败', e.message, 'error')
    }
  }

  async function deleteModel(model: Model) {
    if (!confirm(`确定删除模型「${model.display_name}」？此操作不可撤销。`)) return
    try {
      await api(`/api/anatomy/models/${model.id}`, { method: 'DELETE' })
      useAppStore().showToast('模型已删除', '', 'success')
      if (selectedModel.value?.id === model.id) closeModelDetail()
      await loadModels()
    } catch (e: any) {
      useAppStore().showToast('删除失败', e.message, 'error')
    }
  }

  function switchAnatomyTab(tab: 'operators' | 'models') {
    anatomyTab.value = tab
    if (tab === 'operators') {
      loadOperators()
      loadCategories()
    } else {
      loadModels()
    }
  }

  return {
    anatomyTab,
    operators, operatorsLoading, operatorFilterCategory, operatorSearch,
    showOperatorDetail, selectedOperator, showOperatorEditor,
    operatorEditorMode, operatorForm, operatorTagInput,
    operatorParamsSchemaValid, operatorParamsSchemaError,
    operatorCategoryOptions, showCategoryManager, categoryManagerLoading,
    categoryList, editingCategory, categoryForm, categoryFormMode,
    models, modelsLoading, modelSearch, modelFilterCategory,
    selectedModel, showModelDetail, modelDetailLoading,
    showModelEditor, modelEditorMode, modelForm, editingArchitecture,
    modelTagInput, modelFormSnapshot, modelCategoryOptions,
    loadOperators, operatorById, viewOperatorDetail, closeOperatorDetail,
    editFromDetail, openNewOperator, openEditOperator, closeOperatorEditor,
    addOperatorTag, removeOperatorTag, validateParamsSchema, saveOperator, deleteOperator,
    loadCategories, openCategoryManager, loadCategoryList, openEditCategory,
    saveCategory, moveCategory, deleteCategory,
    loadModels, viewModel, closeModelDetail,
    openNewModel, openEditModel, closeModelEditor,
    addModelTag, removeModelTag,
    addStage, addRepeatBlock, removeStage, addStageBefore, addRepeatBlockBefore,
    moveStageUp, moveStageDown, onStageOperatorChange,
    addRepeatBlockContent, removeRepeatBlockContent,
    addStageToContent, removeStageFromContent,
    saveModel, deleteModel, switchAnatomyTab,
  }
})