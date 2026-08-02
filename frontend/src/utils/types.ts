export interface Toast {
  id: number
  title: string
  msg: string
  type: 'info' | 'success' | 'error' | 'warning' | 'undo'
  undo?: boolean
  undoCallback?: () => void
  _timer?: ReturnType<typeof setTimeout>
}

export interface ConfirmOptions {
  title?: string
  message?: string
  confirmText?: string
  cancelText?: string
  danger?: boolean
  showKnowledgeSyncCheckbox?: boolean
  knowledgeSyncChecked?: boolean
}

export interface ConfirmDialogState {
  show: boolean
  title: string
  message: string
  confirmText: string
  cancelText: string
  danger: boolean
  resolve: ((value: { confirmed: boolean; syncDeleteKnowledge: boolean }) => void) | null
  showKnowledgeSyncCheckbox: boolean
  knowledgeSyncChecked: boolean
}

export interface Area {
  id: string
  name: string
}

export interface User {
  id: number
  name: string
  github_id: string | null
}

export interface Issue {
  number: number
  title: string
  body?: string
  state: 'open' | 'closed'
  type: 'issue'
  author: string
  area: string
  repo?: string
  created_at: string
  updated_at: string
  is_new?: boolean
  watchlist_note?: string
  watchlist_assignee_id?: number | null
  _linked_tasks?: any[]
  [key: string]: any
}

export interface PR {
  pr_number: number
  number?: number
  title: string
  body?: string
  state: 'open' | 'closed' | 'merged'
  type: 'pr'
  author: string
  area: string
  repo?: string
  created_at: string
  updated_at: string
  branch?: string
  conflict_detected?: boolean
  ci_status?: 'pass' | 'fail' | 'pending' | 'unknown'
  is_new?: boolean
  watchlist_note?: string
  watchlist_assignee_id?: number | null
  _linked_tasks?: any[]
  [key: string]: any
}

export interface WatchlistItem {
  number: number
  item_type: 'pr' | 'issue'
  title: string
  url: string
  added_at: string
  repo?: string
  note?: string
  assignee_id?: number | null
  linked_tasks?: any[]
  state?: string
  area?: string
  issue_type?: string
}

export interface TodoTask {
  id: number
  title: string
  description?: string
  status: 'todo' | 'in_progress' | 'done' | 'cancelled'
  priority: 'P0' | 'P1' | 'P2' | 'P3'
  source: string
  area?: string
  assignee_id?: number | null
  due_date?: string
  created_at: string
  updated_at: string
  related_refs?: any[]
  tags?: string[]
  dedup_check_result?: any
  has_dedup_check?: boolean
  has_ai_insight?: boolean
  latest_insight_report_id?: number
  children?: TodoTask[]
  parent_id?: number | null
  subtask_count?: number
  subtask_done_count?: number
}

export interface IntelReport {
  id: number
  title: string
  task_id: number
  sources: string[]
  excluded_sources?: string[]
  extra_prompt?: string
  created_at: string
  status: 'generating' | 'completed' | 'failed'
  category?: string
  word_count: number
  error_message?: string
  content?: string
  task_title?: string
}

export interface Article {
  id: number
  title: string
  content?: string
  area?: string
  tags?: string[]
  user_id?: number | null
  user_name?: string | null
  status: 'draft' | 'published'
  created_at: string
  updated_at: string
  code_refs_count?: number
  valid_refs_count?: number
  outdated_refs_count?: number
}

export interface Operator {
  id: number
  name: string
  display_name: string
  description?: string
  category: string
  params_schema?: any
  input_shape_desc?: string
  output_shape_desc?: string
  vllm_code_refs?: any[]
  tags?: string[]
  user_id?: number | null
  created_at?: string
  updated_at?: string
}

export interface Model {
  id: number
  name: string
  display_name: string
  description?: string
  category: string
  architecture?: any[]
  params_summary?: any
  tags?: string[]
  user_id?: number | null
  created_at?: string
  updated_at?: string
}

export interface PRDetails {
  pr: {
    body: string
    [key: string]: any
  }
  [key: string]: any
}

export interface IssueDetails {
  body: string
  [key: string]: any
}

export interface RepoConfig {
  id: number
  repo: string
  clone_url: string
  branch: string
  last_synced_at: string | null
  commit_sha: string | null
  status: string
  tracked: boolean
  created_at: string
  updated_at: string
}