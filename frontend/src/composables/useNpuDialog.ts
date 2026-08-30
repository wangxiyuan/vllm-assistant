/**
 * 应用内 confirm / prompt 对话框（替代浏览器原生 confirm/prompt/alert）
 *
 * 模块级单例状态：任意组件通过 useNpuDialog() 发起，
 * <NpuDialog />（挂载在各 NPU 视图中）负责渲染与收集结果。
 *
 * 用法：
 *   const dialog = useNpuDialog()
 *   if (await dialog.confirm('删除该模板？', '删除确认')) { ... }
 *   const name = await dialog.prompt('模板名称：', '输入')
 *   dialog.toastError('保存失败', err.message)  // 复用全局 toast
 */
import { reactive } from 'vue'

interface NpuDialogState {
  visible: boolean
  kind: 'confirm' | 'prompt'
  title: string
  message: string
  inputValue: string
  placeholder: string
  resolve: ((v: any) => void) | null
}

// 模块级单例：跨组件共享同一对话框状态
const state = reactive<NpuDialogState>({
  visible: false,
  kind: 'confirm',
  title: '',
  message: '',
  inputValue: '',
  placeholder: '',
  resolve: null,
})

export function useNpuDialog() {
  function confirm(message: string, title = '请确认'): Promise<boolean> {
    return new Promise(resolve => {
      state.kind = 'confirm'
      state.title = title
      state.message = message
      state.inputValue = ''
      state.placeholder = ''
      state.resolve = resolve
      state.visible = true
    })
  }

  function prompt(message: string, title = '输入', defaultValue = '', placeholder = ''): Promise<string | null> {
    return new Promise(resolve => {
      state.kind = 'prompt'
      state.title = title
      state.message = message
      state.inputValue = defaultValue
      state.placeholder = placeholder
      state.resolve = resolve
      state.visible = true
    })
  }

  function accept() {
    if (!state.visible) return
    state.visible = false
    const value = state.kind === 'prompt' ? state.inputValue.trim() : true
    state.resolve?.(state.kind === 'prompt' ? (value || null) : value)
    state.resolve = null
  }

  function cancel() {
    if (!state.visible) return
    state.visible = false
    state.resolve?.(state.kind === 'prompt' ? null : false)
    state.resolve = null
  }

  /** 错误通知：复用全局 toast（代替原生 alert） */
  function toastError(title: string, err?: unknown) {
    import('@/stores/app').then(({ useAppStore }) => {
      const msg = err instanceof Error ? err.message : (err ? String(err) : '')
      useAppStore().showToast(title, msg, 'error')
    })
  }

  /** 成功通知 */
  function toastSuccess(title: string, msg = '') {
    import('@/stores/app').then(({ useAppStore }) => {
      useAppStore().showToast(title, msg, 'success')
    })
  }

  return { state, confirm, prompt, accept, cancel, toastError, toastSuccess }
}
