"""形状表达式与参数表达式求值引擎。

支持三类"可展开"表达式：
  1. ${...} 模板 —— 在 port_bind / loop 等场景，把 ${expr} 展开为绑定值，
     expr 可以是 config.xxx 引用、并行配置、字面量或算术表达式。
  2. 形状表达式（shape）—— 如 "[B, S, H]"，其中维度可以是符号/算术表达式，
     用已解析的符号表求值求 dim 数值。
  3. condition —— 布尔表达式，返回 True/False，决定子积木/步骤是否参与。

求值器只做受控的算术与比较，禁止任意代码执行（安全沙箱）。
"""
from __future__ import annotations

import ast
import operator
import re
from typing import Any, Dict, List, Optional

TEMPLATE_RE = re.compile(r"\$\{([^}]+)\}")


class ShapeExpressionError(ValueError):
    pass


# ---- 受控表达式求值（ast 安全） ----
_BIN_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow,
    ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv,
}
_UNARY_OPS = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_CMP_OPS = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
    ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
    ast.Is: lambda a, b: a is b, ast.IsNot: lambda a, b: a is not b,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
}
_BOOL_OPS = {ast.And: lambda a, b: bool(a) and bool(b), ast.Or: lambda a, b: bool(a) or bool(b)}


def _eval_node(node: ast.AST, ctx: Dict[str, Any]):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, ctx)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if hasattr(node, "id"):
            if node.id in ctx:
                return ctx[node.id]
            raise ShapeExpressionError(f"未解析的符号: {node.id}")
        if hasattr(node, "name") and node.name in ctx:
            return ctx[node.name]
        raise ShapeExpressionError(f"未解析的符号: {getattr(node, 'id', getattr(node, 'name', '?'))}")
    if isinstance(node, ast.NamedExpr):  # walrus 禁止
        raise ShapeExpressionError("表达式内不允许 walrus 操作符")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_eval_node(node.left, ctx), _eval_node(node.right, ctx))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand, ctx))
    if isinstance(node, ast.BoolOp) and type(node.op) in _BOOL_OPS:
        vals = [_eval_node(v, ctx) for v in node.values]
        if type(node.op) is ast.And:
            out = True
            for v in vals:
                out = out and bool(v)
            return out
        else:
            out = False
            for v in vals:
                out = out or bool(v)
            return out
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _CMP_OPS:
        left = _eval_node(node.left, ctx)
        right = _eval_node(node.comparators[0], ctx)
        return _CMP_OPS[type(node.ops[0])](left, right)
    if isinstance(node, ast.Call):
        # 仅允许少数安全内建函数
        if isinstance(node.func, ast.Name):
            name = getattr(node.func, "id", None) or getattr(node.func, "name", None)
            if name in ("int", "float", "len", "round", "max", "min", "abs", "bool"):
                args = [_eval_node(a, ctx) for a in node.args]
                return {"int": int, "float": float, "len": len, "round": round,
                        "max": max, "min": min, "abs": abs, "bool": bool}[name](*args)
        raise ShapeExpressionError("表达式不允许函数调用")
    if isinstance(node, ast.List):
        return [_eval_node(e, ctx) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(e, ctx) for e in node.elts)
    if isinstance(node, ast.Subscript):
        val = _eval_node(node.value, ctx)
        sl = node.slice
        if isinstance(sl, ast.Constant):
            idx = sl.value
            return val[idx]
        raise ShapeExpressionError("仅支持整数下标")
    if isinstance(node, ast.Attribute):
        # 形如 x.y —— 用于条件表达式如 config.is_moe
        base = _eval_node(node.value, ctx)
        if isinstance(base, dict):
            if node.attr in base:
                return base[node.attr]
            raise ShapeExpressionError(f"缺少字段: {node.attr}")
        return getattr(base, node.attr, None)
    raise ShapeExpressionError(f"不支持的表达式节点: {type(node).__name__}")


def eval_expression(expr: Any, ctx: Dict[str, Any]) -> Any:
    """安全求值一个表达式字符串。expr 可为数字/字符串符号原样返回。"""
    if isinstance(expr, (int, float, bool)):
        return expr
    if isinstance(expr, str):
        s = expr.strip()
        if s.startswith("${") and s.endswith("}"):
            s = s[2:-1]
        try:
            tree = ast.parse(s, mode="eval")
            return _eval_node(tree, ctx)
        except ShapeExpressionError:
            raise
        except SyntaxError as e:
            raise ShapeExpressionError(f"表达式语法错误: {s} ({e})") from e
    if isinstance(expr, list):
        return [eval_expression(e, ctx) for e in expr]
    return expr


# ---- config 上下文构建 ----
def build_context(config: Optional[dict] = None,
                  parallel: Optional[dict] = None,
                  loop_vars: Optional[dict] = None) -> Dict[str, Any]:
    """构建求值上下文：config（嵌套文本配置）、parallel、loop_vars。

    同时暴露便于条件判断的辅助对象（config.is_moe 等）。config 为 HF config dict。
    """
    ctx: Dict[str, Any] = {}
    if loop_vars:
        ctx.update(loop_vars)
    # 顶层并列放置，便于 ${config.xxx} 与 ${loop_index} 混合
    cfg = dict(config or {})
    ctx["config"] = cfg
    # 兼容嵌套 text_config
    if isinstance(config, dict) and "text_config" in config:
        text = config["text_config"]
        folded = dict(cfg)
        folded.update(text)
        ctx["config"] = folded
    if parallel:
        ctx["parallel"] = parallel
    return ctx


# ---- 模板展开（${...}）----
def resolve_template(value: Any, ctx: Dict[str, Any]) -> Any:
    """把字符串中的 ${expr} 逐一求值替换。

    若替换后的字符串整体仍是可求值的算术表达式（如 "(4096 * 288)"），
    则继续求值到数值；否则原样返回字符串。
    """
    if isinstance(value, str):
        if TEMPLATE_RE.search(value):
            def _repl(m: "re.Match[str]") -> str:
                try:
                    return str(eval_expression(m.group(1), ctx))
                except ShapeExpressionError as e:
                    raise ShapeExpressionError(f"{value} 中模板求值失败: {e}") from e
            replaced = TEMPLATE_RE.sub(_repl, value)
            # 尝试整体求值（去除占位引用后的纯算术/字面量）
            try:
                return eval_expression(replaced, ctx)
            except ShapeExpressionError:
                return replaced
        return value
    if isinstance(value, list):
        return [resolve_template(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: resolve_template(v, ctx) for k, v in value.items()}
    return value


# ---- 形状表达式 ----
def _tokenize_shape(shape: str) -> List[str]:
    s = shape.strip().strip("[]")
    if not s:
        return []
    # 按逗号分割，但保留括号内
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([{":
            depth += 1
            cur += ch
        elif ch in ")]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def eval_shape(shape: Any, symbols: Dict[str, Any]) -> List[str]:
    """把形状表达式解析为字符串 dim 列表；可解析的用数值计算。"""
    if isinstance(shape, list):
        dims = [str(d) for d in shape]
    elif isinstance(shape, str):
        dims = _tokenize_shape(shape)
    else:
        return []
    out = []
    for d in dims:
        d = d.strip()
        if not d:
            continue
        if d.lstrip("-").replace(".", "", 1).isdigit():
            out.append(d)
            continue
        try:
            out.append(str(eval_expression(d, symbols)))
        except ShapeExpressionError:
            out.append(d)  # 保留符号
    return out


# ---- condition 求值（布尔）----
def eval_condition(cond: Any, ctx: Dict[str, Any]) -> bool:
    """求值 condition（可为布尔、字符串表达式或 None=真）。"""
    if cond is None:
        return True
    if isinstance(cond, bool):
        return cond
    if isinstance(cond, str):
        c = cond.strip()
        if c in ("true", "True", "1"):
            return True
        if c in ("false", "False", "0"):
            return False
        # 先解析 ${...} 模板（如 "( ${config.qk_rope_head_dim} > 0 )"）
        if TEMPLATE_RE.search(c):
            c = resolve_template(c, ctx)
            if isinstance(c, (int, float, bool)):
                return bool(c)
            c = str(c)
        return bool(eval_expression(c, ctx))
    return bool(cond)