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
        <select class="select select-sm" v-model="articlesStore.filterStatus">
          <option value="all">全部状态</option>
          <option value="draft">草稿</option>
          <option value="published">已发布</option>
        </select>
        <select class="select select-sm" v-model="articlesStore.filterArea">
          <option value="">全部领域</option>
          <option v-for="area in appliedAreas" :key="area.id" :value="area.id">{{ area.name }}</option>
        </select>
      </div>

      <div class="article-list">
        <div v-for="article in articlesStore.articles" :key="article.id" class="article-card">
          <div class="article-card-header">
            <h3 class="article-title" @click="articlesStore.viewArticle(article)">{{ article.title }}</h3>
            <div class="article-actions">
              <button class="btn btn-sm" @click="articlesStore.openEditArticle(article)">编辑</button>
              <button class="btn btn-sm btn-ghost" @click="articlesStore.deleteArticle(article)">删除</button>
            </div>
          </div>
          <div class="article-meta">
            <span class="badge" :class="article.status === 'published' ? 'badge-published' : 'badge-draft'">
              {{ article.status === 'published' ? '已发布' : '草稿' }}
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
                    placeholder="支持 Markdown 格式…" @keydown="(e: any) => {
                      if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); articlesStore.saveArticle() }
                      if ((e.ctrlKey || e.metaKey) && e.key === 'p') { e.preventDefault(); articlesStore.previewArticle() }
                    }"></textarea>
        </div>
      </div>
      <div v-if="articlesStore.editorSubView === 'preview'" class="editor-preview">
        <div class="preview-content" v-html="articlesStore.previewHtml"></div>
      </div>
    </template>

    <!-- Article detail view -->
    <template v-if="articlesStore.articleViewOpen">
      <div class="detail-header">
        <button class="btn btn-sm" @click="articlesStore.closeArticleView()">← 返回</button>
        <div class="detail-actions">
          <button class="btn btn-sm" @click="articlesStore.validateArticle(articlesStore.selectedArticle!)">验证引用</button>
          <button class="btn btn-sm" @click="articlesStore.openEditArticle(articlesStore.selectedArticle!)">编辑</button>
        </div>
      </div>
      <div v-if="articlesStore.articleDetailLoading" class="detail-loading">加载中…</div>
      <div v-else class="detail-content">
        <div class="article-toc" v-if="articlesStore.articleToc.length > 0">
          <h4>目录</h4>
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
