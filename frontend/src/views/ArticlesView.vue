<script setup lang="ts">
import { onMounted, onUnmounted, ref, nextTick, computed, watch } from 'vue'
import ChatDrawer from '@/components/ai/ChatDrawer.vue'
import { useArticlesStore } from '@/stores/articles'
import { useAppStore } from '@/stores/app'
import { useUsersStore } from '@/stores/users'
import { timeAgo } from '@/utils/helpers'
import Icon from '@/components/common/Icon.vue'
import CommentSection from '@/components/common/CommentSection.vue'

const articlesStore = useArticlesStore()
const appStore = useAppStore()
const usersStore = useUsersStore()

const activeHeadingId = ref<string | null>(null)

let scrollEl: HTMLElement | null = null

function updateActiveHeading() {
  const headings = articlesStore.articleToc
  if (!headings.length || !scrollEl) return
  const scrollRect = scrollEl.getBoundingClientRect()
  const threshold = scrollRect.top + 80
  let active: string | null = null
  for (const h of headings) {
    const el = document.getElementById(h.id)
    if (!el) continue
    const top = el.getBoundingClientRect().top
    if (top <= threshold) active = h.id
    else break
  }
  activeHeadingId.value = active
}

onMounted(() => {
  articlesStore.loadArticles()
  usersStore.loadUsers()
  scrollEl = document.querySelector('.main')
  scrollEl?.addEventListener('scroll', updateActiveHeading, { passive: true })
})

onUnmounted(() => {
  scrollEl?.removeEventListener('scroll', updateActiveHeading)
})

const appliedAreas = computed(() => {
  return appStore.areas
})

// Recompute active heading whenever the article's HTML or TOC changes
watch(
  () => [articlesStore.articleRenderedHtml, articlesStore.articleToc],
  () => {
    nextTick(() => updateActiveHeading())
  },
)

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
    <!-- Article list view -->
    <template v-if="!articlesStore.editorOpen && !articlesStore.articleViewOpen">
      <div class="view-header">
        <h2 class="view-title">技术Blog</h2>
        <div class="view-actions">
          <button class="btn btn-sm" @click="openAIChat('article')">✨ AI 帮我写</button>
          <button class="btn btn-primary btn-sm" @click="articlesStore.openNewArticle()">+ 写文章</button>
          <span class="view-stats">{{ articlesStore.articleStatsText }}</span>
        </div>
      </div>

      <div class="article-filters">
        <select class="select select-sm" v-model="articlesStore.filterArea" @change="articlesStore.loadArticles()">
          <option value="">所有领域</option>
          <option v-for="area in appliedAreas" :key="area.id" :value="area.id">{{ area.name }}</option>
        </select>
        <select class="select select-sm" v-model="articlesStore.filterStatus" @change="articlesStore.loadArticles()">
          <option value="all">全部状态</option>
          <option value="draft">草稿</option>
          <option value="published">已发布</option>
          <option value="archived">已归档</option>
        </select>
        <select class="select select-sm" v-model="articlesStore.sortBy" @change="articlesStore.loadArticles()">
          <option value="updated">最近更新</option>
          <option value="created">最近创建</option>
          <option value="title">标题</option>
        </select>
      </div>

      <div class="article-list">
        <div v-for="article in articlesStore.articles" :key="article.id" class="article-card" @click="articlesStore.viewArticle(article)">
          <div class="article-card-header">
            <h3 class="article-title">{{ article.title }}</h3>
            <div class="card-action-row article-actions">
              <button class="card-action-btn" @click.stop="articlesStore.openEditArticle(article)" title="编辑文章">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                编辑
              </button>
              <button class="card-action-btn is-danger" @click.stop="articlesStore.deleteArticle(article)" :disabled="articlesStore.deletingArticle" title="删除文章">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                删除
              </button>
            </div>
          </div>
          <div class="article-meta">
            <span class="badge" :class="article.status === 'published' ? 'badge-published' : article.status === ('archived' as string) ? 'badge-archived' : 'badge-draft'">
              {{ article.status === 'published' ? '已发布' : article.status === ('archived' as string) ? '已归档' : '草稿' }}
            </span>
            <span v-if="article.area" class="article-area">{{ appStore.areaName(article.area) }}</span>
            <span v-if="article.user_name" class="article-author article-author-icon"><Icon name="pen" :size="11" /> {{ article.user_name }}</span>
            <span>{{ timeAgo(article.updated_at) }}</span>
            <span :class="articlesStore.refStatusClass(article)">{{ articlesStore.refStatusText(article) }}</span>
          </div>
          <div v-if="article.tags && article.tags.length > 0" class="article-tags">
            <span v-for="tag in article.tags" :key="tag" class="tag">{{ tag }}</span>
          </div>
        </div>
      </div>
    </template>

    <!-- Article editor -->
    <template v-if="articlesStore.editorOpen">
      <div class="editor-header">
        <div class="editor-header-left">
          <h2 class="view-title">{{ articlesStore.editorMode === 'create' ? '新建文章' : '编辑文章' }}</h2>
        </div>
        <div class="editor-actions">
          <button class="btn btn-sm" @click="articlesStore.closeEditor()">取消</button>
          <button class="btn btn-primary btn-sm" @click="articlesStore.saveArticle()">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
            保存 <span style="opacity:0.7">(Ctrl+S)</span>
          </button>
        </div>
      </div>
      <div class="editor-tab-bar tab-bar" style="margin-bottom:var(--space-4)">
        <button class="tab" :class="{ active: articlesStore.editorSubView === 'editor' }"
                @click="articlesStore.editorSubView = 'editor'">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:4px"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          编辑
        </button>
        <button class="tab" :class="{ active: articlesStore.editorSubView === 'preview' }"
                @click="articlesStore.switchPreviewTab()">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:4px"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
          预览 <span class="text-tertiary">(Ctrl+P)</span>
        </button>
      </div>
      <div v-show="articlesStore.editorSubView === 'editor'" class="editor-body">
        <div class="form-group">
          <input type="text" class="input input-lg" v-model="articlesStore.form.title" placeholder="文章标题" />
        </div>
        <div class="editor-meta-fields">
          <select class="select" v-model="articlesStore.form.area">
            <option value="">选择领域</option>
            <option v-for="area in appliedAreas" :key="area.id" :value="area.id">{{ area.name }}</option>
          </select>
          <select class="select" v-model="articlesStore.form.status">
            <option value="draft">草稿</option>
            <option value="published">已发布</option>
            <option value="archived">已归档</option>
          </select>
          <select class="select" v-model.number="articlesStore.form.user_id">
            <option :value="null">选择作者</option>
            <option v-for="u in usersStore.users" :key="u.id" :value="u.id">{{ u.name }}</option>
          </select>
          <div class="tag-input">
            <input type="text" class="input" v-model="articlesStore.editorTagInput"
                   placeholder="标签" @keydown.enter.prevent="articlesStore.addEditorTag()" />
            <span v-for="tag in articlesStore.form.tags" :key="tag" class="tag">
              {{ tag }} <button class="tag-remove" @click="articlesStore.removeEditorTag(tag)">&times;</button>
            </span>
          </div>
        </div>
        <div class="editor-toolbar">
          <button class="btn btn-sm" @click="articlesStore.openInsertRef()" title="插入代码引用">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
            插入代码引用
          </button>
        </div>
        <div class="form-group" style="flex:1;">
          <textarea class="textarea editor-textarea" v-model="articlesStore.form.content"
                    placeholder="支持 Markdown 格式…&#10;使用 `vllm/engine/core.py:10-20` 格式引用代码片段&#10;使用 `vllm-ascend/ascend/backend.py:30` 引用其他仓库" @keydown="(e: any) => {
                      if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); articlesStore.saveArticle() }
                      if ((e.ctrlKey || e.metaKey) && e.key === 'p') { e.preventDefault(); articlesStore.switchPreviewTab() }
                    }"></textarea>
        </div>
      </div>
      <div v-show="articlesStore.editorSubView === 'preview'" class="editor-preview">
        <div v-if="!articlesStore.previewHtml" class="empty-state is-compact" style="padding:var(--space-10) 0;">
          <p>点击「预览」生成预览内容</p>
        </div>
        <div v-else class="preview-content" v-html="articlesStore.previewHtml"></div>
      </div>
    </template>

    <!-- Insert Code Ref Modal -->
    <Teleport to="body">
      <div v-if="articlesStore.showInsertRef" class="modal-backdrop" @click="articlesStore.closeInsertRef()">
        <div class="modal" @click.stop>
          <div class="modal-header">
            <h3>插入代码引用</h3>
            <button class="modal-close" @click="articlesStore.closeInsertRef()" title="关闭">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
          <div class="modal-body">
            <div class="form-row" style="align-items:flex-end;">
              <div class="field" style="flex:0 0 140px;">
                <label class="form-label">仓库</label>
                <select class="select" v-model="articlesStore.insertRef.repo" @change="articlesStore.loadCachedFiles()">
                  <option v-for="repo in articlesStore.repoOptions" :key="repo" :value="repo">{{ repo }}</option>
                </select>
              </div>
              <div class="field" style="flex:1;">
                <label class="form-label">文件路径</label>
                <div style="display:flex;gap:4px;">
                  <input class="input" type="text" v-model="articlesStore.insertRef.file_path" placeholder="搜索或输入文件路径" @input="articlesStore.loadCachedFiles()" style="flex:1;" list="cached-file-list" />
                  <datalist id="cached-file-list">
                    <option v-for="f in articlesStore.cacheFiles" :key="f" :value="f" />
                  </datalist>
                </div>
              </div>
            </div>
            <div class="form-row" style="align-items:flex-end;">
              <div class="field" style="flex:0 0 120px;">
                <label class="form-label">起始行</label>
                <input class="input" type="number" v-model.number="articlesStore.insertRef.line_start" placeholder="10" />
              </div>
              <div class="field" style="flex:0 0 120px;">
                <label class="form-label">结束行</label>
                <input class="input" type="number" v-model.number="articlesStore.insertRef.line_end" placeholder="20（可选）" />
              </div>
              <div class="field" style="flex:0 0 auto;">
                <button class="btn btn-sm" @click="articlesStore.searchCacheFiles()">预览代码</button>
              </div>
            </div>
            <div v-if="articlesStore.insertRefPreview" style="margin-top:var(--space-4);">
              <label class="form-label">代码预览</label>
              <pre class="code-preview" style="max-height:200px;">{{ articlesStore.insertRefPreview }}</pre>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn" @click="articlesStore.closeInsertRef()">取消</button>
            <button class="btn btn-primary" @click="articlesStore.confirmInsertRef()">插入引用</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Article detail view -->
    <template v-if="articlesStore.articleViewOpen">
      <div class="detail-header">
        <button class="btn btn-sm" @click="articlesStore.closeArticleView()">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>
          返回
        </button>
        <div class="detail-action-bar" style="margin-top:0;padding-top:0;border-top:none;">
          <div class="action-bar-secondary">
            <button class="btn btn-sm" @click="articlesStore.openEditArticle(articlesStore.selectedArticle!)">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
              编辑
            </button>
            <button class="btn btn-sm" @click="articlesStore.validateArticle(articlesStore.selectedArticle!, true)" :disabled="articlesStore.validating" title="校验代码引用是否有效（含内容哈希对比）">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
              {{ articlesStore.validating ? '校验中…' : '代码引用校验' }}
            </button>
          </div>
          <div class="action-bar-primary">
            <button class="btn btn-sm btn-danger" @click="articlesStore.deleteArticle(articlesStore.selectedArticle!)" :disabled="articlesStore.deletingArticle">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
              删除
            </button>
          </div>
        </div>
      </div>

      <!-- Validation result -->
      <div v-if="articlesStore.validationResult" class="ai-result" style="margin-bottom:var(--space-4);">
        <div class="ai-result-header">
          <div class="ai-result-title">验证结果</div>
          <button class="btn btn-sm btn-ghost" @click="articlesStore.closeValidation()" title="关闭">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="ai-result-body">
          <p>共 <strong>{{ articlesStore.validationResult.total_refs }}</strong> 个引用，
          <span class="text-success">{{ articlesStore.validationResult.valid_refs }} 有效</span>
          <span v-if="articlesStore.validationResult.invalid_refs > 0" class="text-danger">，{{ articlesStore.validationResult.invalid_refs }} 无效</span>
          </p>
          <div v-for="detail in (articlesStore.validationResult.details || [])" :key="detail.file_path + detail.line_start" class="dedup-item">
            <div :class="detail.is_valid ? 'text-success' : 'text-danger'">
              <span>{{ detail.repo + '/' + detail.file_path + ':' + detail.line_start + '-' + detail.line_end }}</span>
              <span class="ref-check-icon" :class="detail.is_valid ? 'is-valid' : 'is-invalid'"><Icon :name="detail.is_valid ? 'check' : 'x'" :size="11" /></span>
              <span v-if="!detail.is_valid"> {{ detail.reason }}</span>
            </div>
            <div v-if="detail.message" class="text-tertiary">{{ detail.message }}</div>
          </div>
        </div>
      </div>

      <div v-if="articlesStore.articleDetailLoading" class="detail-loading">加载中…</div>
      <div v-else>
        <div class="article-detail-meta">
          <span v-if="articlesStore.selectedArticle?.user_name" class="article-author article-author-icon"><Icon name="pen" :size="11" /> {{ articlesStore.selectedArticle?.user_name }}</span>
          <span v-if="articlesStore.selectedArticle?.area" class="article-area">{{ appStore.areaName(articlesStore.selectedArticle?.area) }}</span>
          <span class="article-date">{{ timeAgo(articlesStore.selectedArticle?.updated_at) }}</span>
        </div>
        <div class="article-content-wrapper">
          <aside v-if="articlesStore.articleToc.length > 0" class="article-toc-sidebar">
          <div class="article-toc-title">目录</div>
          <a v-for="item in articlesStore.articleToc" :key="item.id"
             class="article-toc-item"
             :class="['level-' + item.level, { active: activeHeadingId === item.id }]"
             :href="'#' + item.id"
             @click.prevent="articlesStore.scrollToHeading(item.id)">
            {{ item.text }}
          </a>
        </aside>
        <div class="article-content-body" v-html="articlesStore.articleRenderedHtml"></div>
        </div>
        <CommentSection v-if="articlesStore.selectedArticle" target-type="article" :target-id="articlesStore.selectedArticle.id" />
      </div>
    </template>
    <ChatDrawer :open="aiChatOpen" :intent="aiChatIntent" @close="aiChatOpen = false" />
  </div>
</template>