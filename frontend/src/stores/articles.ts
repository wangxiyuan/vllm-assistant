import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { useAppStore } from './app'
import type { Article } from '@/utils/types'

export const useArticlesStore = defineStore('articles', () => {
  const articles = ref<Article[]>([])
  const loading = ref(false)
  const articlesTotal = ref(0)
  const filterArea = ref('')
  const filterStatus = ref('all')
  const sortBy = ref('updated')
  const sortOrder = ref('desc')

  // Editor
  const editorOpen = ref(false)
  const editorSubView = ref<'editor' | 'preview'>('editor')
  const editorMode = ref<'create' | 'edit'>('create')
  const form = ref({
    id: null as number | null,
    title: '',
    content: '',
    area: '',
    tags: [] as string[],
    user_id: null as number | null,
    status: 'draft',
  })
  const formSnapshot = ref<any>(null)
  const editorTagInput = ref('')

  // Preview
  const previewHtml = ref('')
  const previewRefs = ref<any[]>([])

  // Article detail
  const articleViewOpen = ref(false)
  const selectedArticle = ref<Article | null>(null)
  const articleDetailLoading = ref(false)
  const articleRenderedHtml = ref('')
  const articleEmbeddedCodes = ref<any[]>([])
  const articleToc = ref<any[]>([])
  const articleTocOpen = ref(false)

  // Validation
  const validating = ref(false)
  const validationResult = ref<any>(null)
  const deletingArticle = ref(false)

  // Insert code ref
  const showInsertRef = ref(false)
  const insertRef = ref({ repo: 'vllm', file_path: '', line_start: 1, line_end: 10 })
  const insertRefPreview = ref('')
  const cacheFiles = ref<any[]>([])

  const articleStatsText = computed(() => {
    const total = articles.value.length
    const outdated = articles.value.filter(a => a.outdated_refs_count && a.outdated_refs_count > 0).length
    if (total === 0) return '暂无文章'
    return `共 ${total} 篇文章 · ${outdated} 篇有过时引用`
  })

  const formDirty = computed(() => {
    if (!formSnapshot.value) return false
    const snap = formSnapshot.value
    return snap.title !== form.value.title
      || snap.content !== form.value.content
      || snap.area !== form.value.area
      || snap.status !== form.value.status
      || JSON.stringify(snap.tags) !== JSON.stringify(form.value.tags)
  })

  const repoOptions = ['vllm', 'vllm-ascend']

  function _takeFormSnapshot() {
    formSnapshot.value = {
      title: form.value.title,
      content: form.value.content,
      area: form.value.area,
      status: form.value.status,
      tags: [...form.value.tags],
    }
  }

  function _confirmDiscard(): boolean {
    if (formDirty.value) {
      if (!confirm('有未保存的修改，确定要放弃吗？')) return false
    }
    return true
  }

  async function loadArticles() {
    loading.value = true
    try {
      const params = new URLSearchParams()
      if (filterArea.value) params.set('area', filterArea.value)
      if (filterStatus.value !== 'all') params.set('status', filterStatus.value)
      if (sortBy.value) params.set('sort_by', sortBy.value)
      if (sortOrder.value) params.set('sort_order', sortOrder.value)
      const qs = params.toString()
      const data: any = await api(`/api/articles${qs ? '?' + qs : ''}`)
      articles.value = data.articles || []
      articlesTotal.value = data.total || 0
    } catch (e: any) {
      useAppStore().showToast('加载文章失败', e.message, 'error')
    } finally {
      loading.value = false
    }
  }

  function openNewArticle() {
    if (!_confirmDiscard()) return
    editorMode.value = 'create'
    form.value = { id: null, title: '', content: '', area: '', tags: [], user_id: null, status: 'draft' }
    editorTagInput.value = ''
    articleViewOpen.value = false
    selectedArticle.value = null
    editorOpen.value = true
    editorSubView.value = 'editor'
    previewHtml.value = ''
    previewRefs.value = []
    _takeFormSnapshot()
  }

  function openEditArticle(article: Article) {
    if (!_confirmDiscard()) return
    editorMode.value = 'edit'
    form.value = {
      id: article.id,
      title: article.title || '',
      content: article.content || '',
      area: article.area || '',
      tags: article.tags || [],
      user_id: article.user_id || null,
      status: article.status || 'draft',
    }
    editorTagInput.value = ''
    articleViewOpen.value = false
    // 保留 selectedArticle，关闭编辑器后可以恢复详情视图
    editorOpen.value = true
    editorSubView.value = 'editor'
    previewHtml.value = ''
    previewRefs.value = []
    _takeFormSnapshot()
  }

  function closeEditor() {
    editorOpen.value = false
    editorSubView.value = 'editor'
    formSnapshot.value = null
    // 编辑模式关闭后，恢复文章详情视图
    if (editorMode.value === 'edit' && selectedArticle.value) {
      articleViewOpen.value = true
    }
  }

  function addEditorTag() {
    const t = editorTagInput.value.trim().toLowerCase()
    if (t && !form.value.tags.includes(t)) form.value.tags.push(t)
    editorTagInput.value = ''
  }

  function removeEditorTag(tag: string) {
    form.value.tags = form.value.tags.filter(t => t !== tag)
  }

  async function saveArticle() {
    const title = form.value.title.trim()
    if (!title) {
      useAppStore().showToast('标题不能为空', '', 'error')
      return
    }
    const content = form.value.content
    const body: any = {
      title, content, area: form.value.area || '',
      tags: form.value.tags, user_id: form.value.user_id,
      status: form.value.status || 'draft',
    }
    try {
      if (editorMode.value === 'create') {
        await api('/api/articles', { method: 'POST', body: JSON.stringify(body) })
        useAppStore().showToast('文章已创建', '', 'success')
      } else {
        await api(`/api/articles/${form.value.id}`, { method: 'PUT', body: JSON.stringify(body) })
        useAppStore().showToast('文章已更新', '', 'success')
      }
      editorOpen.value = false
      editorSubView.value = 'editor'
      formSnapshot.value = null
      await loadArticles()
    } catch (e: any) {
      useAppStore().showToast('保存失败', e.message, 'error')
    }
  }

  async function deleteArticle(article: Article) {
    if (deletingArticle.value) return
    if (!confirm(`确定删除文章「${article.title}」？此操作不可撤销。`)) return
    deletingArticle.value = true
    const backup = { ...article }
    try {
      await api(`/api/articles/${article.id}`, { method: 'DELETE' })
      if (selectedArticle.value?.id === article.id) closeArticleView()
      await loadArticles()
      useAppStore().showUndoToast('文章已删除', article.title, async () => {
        try {
          await api('/api/articles', {
            method: 'POST',
            body: JSON.stringify({
              title: backup.title, content: backup.content || '',
              area: backup.area || '', tags: backup.tags || [],
              status: backup.status || 'draft',
            }),
          })
          useAppStore().showToast('已恢复', backup.title, 'success')
          await loadArticles()
        } catch (e: any) {
          useAppStore().showToast('恢复失败', e.message, 'error')
        }
      }, 10000)
    } catch (e: any) {
      useAppStore().showToast('删除失败', e.message, 'error')
    } finally {
      deletingArticle.value = false
    }
  }

  async function previewArticle() {
    const content = form.value.content
    if (!content.trim()) {
      useAppStore().showToast('内容为空', '', 'error')
      return
    }
    try {
      const data: any = await api('/api/articles/preview', {
        method: 'POST',
        body: JSON.stringify({ content }),
      })
      previewHtml.value = data.html || ''
      previewRefs.value = data.refs || []
      articleToc.value = data.toc || []
      editorSubView.value = 'preview'
    } catch (e: any) {
      useAppStore().showToast('预览失败', e.message, 'error')
    }
  }

  function closePreview() {
    editorSubView.value = 'editor'
  }

  async function switchPreviewTab() {
    if (editorSubView.value === 'preview') return
    if (!previewHtml.value) {
      await previewArticle()
    } else {
      editorSubView.value = 'preview'
    }
  }

  async function viewArticle(article: Article) {
    articleViewOpen.value = true
    selectedArticle.value = article
    articleDetailLoading.value = true
    articleRenderedHtml.value = ''
    articleEmbeddedCodes.value = []
    articleToc.value = []
    articleTocOpen.value = false
    try {
      const data: any = await api(`/api/articles/${article.id}/rendered?sync_code=false`)
      articleRenderedHtml.value = data.html || ''
      articleEmbeddedCodes.value = data.embedded_codes || []
      articleToc.value = data.toc || []
    } catch (e: any) {
      articleRenderedHtml.value = `<div class="code-embed-error">加载失败: ${e.message}</div>`
    } finally {
      articleDetailLoading.value = false
    }
  }

  function closeArticleView() {
    articleViewOpen.value = false
    selectedArticle.value = null
    articleRenderedHtml.value = ''
    articleEmbeddedCodes.value = []
    articleToc.value = []
    articleTocOpen.value = false
  }

  function scrollToHeading(id: string) {
    const el = document.getElementById(id)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      articleTocOpen.value = false
    }
  }

  async function validateArticle(article: Article, deep = false) {
    validating.value = true
    validationResult.value = null
    try {
      const data: any = await api(`/api/articles/${article.id}/validate`, {
        method: 'POST',
        body: JSON.stringify({ deep_check: deep }),
      })
      validationResult.value = data
      const msg = data.invalid_refs > 0 ? `${data.invalid_refs} 个引用失效` : '全部引用有效'
      useAppStore().showToast('验证完成', msg, data.invalid_refs > 0 ? 'warning' : 'success')
      await loadArticles()
    } catch (e: any) {
      useAppStore().showToast('验证失败', e.message, 'error')
    } finally {
      validating.value = false
    }
  }

  function closeValidation() {
    validationResult.value = null
  }

  function openInsertRef() {
    showInsertRef.value = true
    insertRef.value = { repo: 'vllm', file_path: '', line_start: 1, line_end: 10 }
    insertRefPreview.value = ''
    cacheFiles.value = []
    loadCachedFiles()
  }

  function closeInsertRef() {
    showInsertRef.value = false
  }

  async function loadCachedFiles() {
    const repo = insertRef.value.repo
    const q = insertRef.value.file_path || ''
    try {
      const data: any = await api(`/api/sync/code/files?repo=${repo}&q=${encodeURIComponent(q)}&limit=50`)
      cacheFiles.value = data.files || []
    } catch (_) {
      // Silent fail, file list is optional UX
    }
  }

  async function searchCacheFiles() {
    if (!insertRef.value.file_path) return
    insertRefPreview.value = '加载中…'
    try {
      const data: any = await api(`/api/sync/code/${encodeURIComponent(insertRef.value.file_path)}?repo=${insertRef.value.repo}`)
      const lines = (data.content || '').split('\n')
      const start = insertRef.value.line_start
      const end = Math.min(insertRef.value.line_end || start, lines.length)
      const snippet = lines.slice(start - 1, end).join('\n')
      insertRefPreview.value = snippet || '(空)'
    } catch (e: any) {
      insertRefPreview.value = `未找到文件: ${e.message}`
    }
  }

  function confirmInsertRef() {
    const ref = insertRef.value
    const lineEnd = ref.line_end || ref.line_start
    const codeRef = `\`${ref.repo}/${ref.file_path}:${ref.line_start}-${lineEnd}\``
    form.value.content = form.value.content + '\n' + codeRef
    showInsertRef.value = false
    useAppStore().showToast('已插入代码引用', '', 'success')
  }

  function refStatusText(article: Article): string {
    if (!article.code_refs_count) return '无引用'
    if (article.outdated_refs_count && article.outdated_refs_count > 0) {
      return `${article.valid_refs_count}/${article.code_refs_count} 有效`
    }
    return `${article.code_refs_count} 引用全部有效`
  }

  function refStatusClass(article: Article): string {
    if (!article.code_refs_count) return ''
    return article.outdated_refs_count && article.outdated_refs_count > 0 ? 'warning' : 'ok'
  }

  return {
    articles, loading, articlesTotal, filterArea, filterStatus, sortBy, sortOrder,
    editorOpen, editorSubView, editorMode, form, formSnapshot, editorTagInput,
    previewHtml, previewRefs,
    articleViewOpen, selectedArticle, articleDetailLoading,
    articleRenderedHtml, articleEmbeddedCodes, articleToc, articleTocOpen,
    validating, validationResult, deletingArticle,
    showInsertRef, insertRef, insertRefPreview, cacheFiles,
    articleStatsText, formDirty, repoOptions,
    loadArticles, openNewArticle, openEditArticle, closeEditor,
    addEditorTag, removeEditorTag, saveArticle, deleteArticle,
    previewArticle, closePreview, switchPreviewTab,
    viewArticle, closeArticleView, scrollToHeading,
    validateArticle, closeValidation,
    openInsertRef, closeInsertRef, loadCachedFiles, searchCacheFiles, confirmInsertRef,
    refStatusText, refStatusClass,
  }
})