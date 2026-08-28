/**
 * resolveConfig.ts —— 将 YAML 中的 ${config.xxx} / ${...} 表达式解析为具体值
 *
 * YAML 的唯一源里 loop.count、port_bind 常写成 "${config.num_hidden_layers}" 等
 * 运行期表达式。config 值由【用户随 YAML 提供】（顶层 config: 字段），
 * 前端读取该 config 求值表达式，不再内置任何模型取值。
 * 未提供的字段保留原文，并在 loop 徽标给出提示。
 */

const TEMPLATE_RE = /\$\{([^}]+)\}/g

/**
 * 求值一个 ${expr} 字符串。ctx 为 config 扁平化映射 + 循环变量。
 * 支持 config.x.y、约束算术（+ - * / 括号）与基础内建。
 */
function evalExpr(expr: string, ctx: Record<string, any>): any {
  const s = expr.trim()
  // 纯 config 引用
  if (/^config\.[A-Za-z_][A-Za-z0-9_]*$/.test(s)) {
    const key = s.split('.')[1]
    return ctx[key]
  }
  // 单符号
  if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(s)) return ctx[s]
  // 算术（安全：仅替换 config.x 引用后 eval 基础算术）
  const withVals = s.replace(/config\.([A-Za-z_][A-Za-z0-9_]*)/g, (_, k) => {
    const v = ctx[k]
    if (typeof v === 'number') return String(v)
    if (typeof v === 'string') return `'${v}'`
    return `undefined`
  }).replace(/\b(true|false)\b/g, 'true')
  try {
    // eslint-disable-next-line no-new-func
    return new Function('return (' + withVals + ')')()
  } catch {
    return undefined
  }
}

/**
 * 解析 ${...} 模板。config 对照表 + 可选 loop 变量。
 */
function resolveTemplate(
  value: any,
  config?: Record<string, any>,
  loopVars?: Record<string, any>,
): { ok: boolean; value: any; unresolved: string } | null {
  if (typeof value !== 'string') return null
  const ctx: Record<string, any> = { ...(config || {}), ...(loopVars || {}) }
  if (!TEMPLATE_RE.test(value)) return { ok: true, value, unresolved: '' }
  const unresolved: string[] = []
  const out = value.replace(TEMPLATE_RE, (_, inner) => {
    const v = evalExpr(inner, ctx)
    if (v !== undefined && v !== null && !Number.isNaN(v)) return String(v)
    unresolved.push(inner)
    return `${inner}`
  })
  // 若整体是纯数值表达式，再求值一次
  let finalVal: any = out
  try {
    if (/^[\d\s+\-*/().]+$/.test(out)) {
      // eslint-disable-next-line no-new-func
      finalVal = new Function('return (' + out + ')')()
    }
  } catch { /* 保留字符串 */ }
  return { ok: unresolved.length === 0, value: finalVal, unresolved: unresolved.join('; ') }
}

/**
 * 求值一个“条件表达式”（如 `not config.tie_word_embeddings`、`config.rope_scaling`）。
 * 支持 config.x 引用、not / ! 取反、&& / ||、括号与布尔/数值比较朴素求值。
 * 返回 { ok, truthy }；truthy 为 null 表示无法确定真值（字段缺失等）。
 */
export function evalCondition(expr: string, config: Record<string, any> = {}): { ok: boolean; truthy: boolean | null } {
  if (expr == null || String(expr).trim() === '') return { ok: false, truthy: null }
  const raw = String(expr).trim()

  // 用安全替换把 config.xxx 换成实际值（JSON 序列化，保真 true/false/字符串/数字）
  const subst = (s: string) =>
    s.replace(/config\.([A-Za-z_][A-Za-z0-9_]*)/g, (_, k: string) => {
      const v = config[k]
      if (v === undefined) return 'undefined'
      if (typeof v === 'string') return JSON.stringify(v)
      return String(v) // number / boolean -> 直接展开
    })

  const substituted = subst(raw)

  // 若引用了未定义的 config 字段，视作无法求值
  if (/\bundefined\b/.test(substituted)) return { ok: false, truthy: null }

  // 把 Python 风格 keywords 转成 JS（not -> !，and -> &&，or -> ||）
  const jsSrc = substituted
    .replace(/\bnot\s+/g, '!')
    .replace(/^!/, '!')
    .replace(/\band\b/g, '&&')
    .replace(/\bor\b/g, '||')

  try {
    // eslint-disable-next-line no-new-func
    const val = new Function('return (' + jsSrc + ')')()
    return { ok: val !== undefined, truthy: val === undefined ? null : !!val }
  } catch {
    return { ok: false, truthy: null }
  }
}

/**
 * 便捷：把 loop.count 等解析为显示字符串；解析不出时保留原文。
 */
export function resolveLoopCount(
  raw: any,
  config?: Record<string, any>,
  loopVars?: Record<string, any>,
): { label: string; ok: boolean; unresolved: string } {
  if (raw == null || raw === '') return { label: '?', ok: false, unresolved: '' }
  const r = resolveTemplate(raw, config, loopVars)
  if (!r) return { label: String(raw), ok: true, unresolved: '' }
  if (r.ok) return { label: String(r.value), ok: true, unresolved: '' }
  return { label: String(raw), ok: false, unresolved: r.unresolved }
}