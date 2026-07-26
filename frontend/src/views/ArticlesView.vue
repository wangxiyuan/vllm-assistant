<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useArticlesStore } from '@/stores/articles'
import { useAppStore } from '@/stores/app'
import { timeAgo } from '@/utils/helpers'

const articlesStore = useArticlesStore()
const appStore = useAppStore()

onMounted(() => {
  articlesStore.loadArticles()
})

const appliedAreas = computed(() => {
  return appStore.areas
})
</script>

<template>
  <div class="view-container">
    <!-- Article list view -->
    <template v-if="!articlesStore.editorOpen && !articlesStore.articleViewOpen">
      <div class="view-header">
        <h2 class="view-title">技术Blog</h2>
        <div class="view-actions">
          <span class="view-stats">{{ articlesStore.articleStatsText }}</span>
          <button class="btn btn-primary btn-sm" @click="articlesStore.openNewArticle()">+ 写文章</button>
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
            <div class="article-actions">
              <button class="btn btn-sm" @click.stop="articlesStore.openEditArticle(article)">编辑</button>
              <button class="btn btn-sm btn-ghost" @click.stop="articlesStore.validateArticle(article, false)" :disabled="articlesStore.validating" title="验证引用">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
              </button>
              <button class="btn btn-sm btn-ghost" @click.stop="articlesStore.deleteArticle(article)" :disabled="articlesStore.deletingArticle" style="color:var(--signal-red);">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
              </button>
            </div>
          </div>
          <div class="article-meta">
            <span class="badge" :class="article.status === 'published' ? 'badge-published' : article.status === ('archived' as string) ? 'badge-archived' : 'badge-draft'">
              {{ article.status === 'published' ? '已发布' : article.status === ('archived' as string) ? '已归档' : '草稿' }}
            </span>
            <span v-if="article.area" class="article-area">{{ appStore.areaName(article.area) }}</span>
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
        <h2 class="view-title">{{ articlesStore.editorMode === 'create' ? '新建文章' : '编辑文章' }}</h2>
        <div class="editor-actions">
          <button class="btn btn-sm" @click="articlesStore.openInsertRef()" title="插入代码引用">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
            插入代码引用
          </button>
          <button class="btn btn-sm" @click="articlesStore.closeEditor()">取消</button>
          <button class="btn btn-sm" @click="articlesStore.previewArticle()">预览 (Ctrl+P)</button>
          <button class="btn btn-primary btn-sm" @click="articlesStore.saveArticle()">保存 (Ctrl+S)</button>
        </div>
      </div>
      <div v-if="articlesStore.editorSubView === 'editor'" class="editor-body">
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
          <div class="tag-input">
            <input type="text" class="input" v-model="articlesStore.editorTagInput"
                   placeholder="标签" @keydown.enter.prevent="articlesStore.addEditorTag()" />
            <span v-for="tag in articlesStore.form.tags" :key="tag" class="tag">
              {{ tag }} <button class="tag-remove" @click="articlesStore.removeEditorTag(tag)">&times;</button>
            </span>
          </div>
        </div>
        <div class="form-group" style="flex:1;">
          <textarea class="textarea editor-textarea" v-model="articlesStore.form.content"
                    placeholder="支持 Markdown 格式…&#10;使用 `vllm/engine/core.py:10-20` 格式引用代码片段&#10;使用 `vllm-ascend/ascend/backend.py:30` 引用其他仓库" @keydown="(e: any) => {
                      if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); articlesStore.saveArticle() }
                      if ((e.ctrlKey || e.metaKey) && e.key === 'p') { e.preventDefault(); articlesStore.previewArticle() }
                    }"></textarea>
        </div>
      </div>
      <div v-if="articlesStore.editorSubView === 'preview'" class="editor-preview">
        <div class="preview-content" v-html="articlesStore.previewHtml"></div>
      </div>
    </template>

    <!-- Insert Code Ref Modal -->
    <Teleport to="body">
      <div v-if="articlesStore.showInsertRef" class="modal-backdrop" @click="articlesStore.closeInsertRef()">
        <div class="modal" @click.stop>
          <h3 class="modal-title">插入代码引用</h3>
          <div class="form-row">
            <select class="select" v-model="articlesStore.insertRef.repo">
              <option value="vllm">vllm</option>
              <option value="vllm-ascend">vllm-ascend</option>
            </select>
            <input class="input" type="text" v-model="articlesStore.insertRef.file_path" placeholder="文件路径 (如 engine/core.py)" style="flex:1;" />
          </div>
          <div class="form-row">
            <input class="input" type="number" v-model.number="articlesStore.insertRef.line_start" placeholder="起始行" style="width:100px;" />
            <input class="input" type="number" v-model.number="articlesStore.insertRef.line_end" placeholder="结束行（可选）" style="width:100px;" />
            <button class="btn btn-sm" @click="articlesStore.searchCacheFiles()">预览代码</button>
          </div>
          <div v-if="articlesStore.insertRefPreview" style="margin:var(--space-4) 0;padding:12px;background:var(--bg-secondary);border-radius:6px;">
            <pre style="font-size:11px;max-height:200px;overflow:auto;">{{ articlesStore.insertRefPreview }}</pre>
          </div>
          <div class="modal-actions">
            <button class="btn" @click="articlesStore.closeInsertRef()">取消</button>
            <button class="btn btn-primary" @click="articlesStore.confirmInsertRef()">插入</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Article detail view -->
    <template v-if="articlesStore.articleViewOpen">
      <div class="detail-header">
        <button class="btn btn-sm" @click="articlesStore.closeArticleView()">← 返回</button>
        <div class="detail-actions">
          <button class="btn btn-sm" @click="articlesStore.validateArticle(articlesStore.selectedArticle!, false)" :disabled="articlesStore.validating">验证引用</button>
          <button class="btn btn-sm" @click="articlesStore.validateArticle(articlesStore.selectedArticle!, true)" :disabled="articlesStore.validating" title="深层验证（含内容哈希对比）">深层验证</button>
          <button class="btn btn-sm" @click="articlesStore.openEditArticle(articlesStore.selectedArticle!)">编辑</button>
          <button class="btn btn-sm btn-ghost" style="color:var(--signal-red);" @click="articlesStore.deleteArticle(articlesStore.selectedArticle!)" :disabled="articlesStore.deletingArticle">删除</button>
        </div>
      </div>

      <!-- Validation result -->
      <div v-if="articlesStore.validationResult" class="ai-result" style="margin-bottom:var(--space-4);">
        <div class="ai-result-header">
          <div class="ai-result-title">验证结果</div>
          <button class="btn btn-sm btn-ghost" @click="articlesStore.closeValidation()">&times;</button>
        </div>
        <div class="ai-result-body">
          <p>共 <strong>{{ articlesStore.validationResult.total_refs }}</strong> 个引用，
          <span style="color:var(--signal-green);">{{ articlesStore.validationResult.valid_refs }} 有效</span>
          <span v-if="articlesStore.validationResult.invalid_refs > 0" style="color:var(--signal-red);">，{{ articlesStore.validationResult.invalid_refs }} 无效</span>
          </p>
          <div v-for="detail in (articlesStore.validationResult.details || [])" :key="detail.file_path + detail.line_start" class="dedup-item" style="font-size:12px;">
            <div :style="'color:' + (detail.is_valid ? 'var(--signal-green)' : 'var(--signal-red)')">
              <span>{{ detail.repo + '/' + detail.file_path + ':' + detail.line_start + '-' + detail.line_end }}</span>
              <span>{{ detail.is_valid ? ' ✓' : ' ✗ ' + detail.reason }}</span>
            </div>
            <div v-if="detail.message" style="color:var(--text-tertiary);">{{ detail.message }}</div>
          </div>
        </div>
      </div>

      <div v-if="articlesStore.articleDetailLoading" class="detail-loading">加载中…</div>
      <div v-else class="detail-content">
        <div class="article-toc" v-if="articlesStore.articleToc.length > 0">
          <h4>📖 目录</h4>
          <ul>
            <li v-for="item in articlesStore.articleToc" :key="item.id" class="toc-item" :class="'toc-h' + item.level">
              <a :href="'#' + item.id" @click.prevent="articlesStore.scrollToHeading(item.id)">{{ item.text }}</a>
            </li>
          </ul>
        </div>
        <div class="article-rendered" v-html="articlesStore.articleRenderedHtml"></div>
      </div>
    </template>
  </div>
</template>