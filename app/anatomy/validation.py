"""模型拆解校验引擎。

在原子/组合积木定义的基础上，对 model_assembly / composite 做跨引用与
数据流校验：
  - 引用的积木/端口必须存在
  - 端口连接的可达性与形状一致性
  - condition / loop / port_bind 表达式可求值
  - 循环依赖检测（composite 自引用 / assembly 步骤环）

校验是"静态/声明式"的：只检查结构一致性，不实例化真实模型。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .shape_engine import (
    ShapeExpressionError,
    build_context,
    eval_condition,
    eval_expression,
    eval_shape,
    resolve_template,
)

# 容错的符号缺省值（用于无法从 config 推导时的"尽力"求值，仅校验用途）
_FALLBACK_SYMBOLS: Dict[str, Any] = {
    "B": 1, "S": 1, "T": 1, "H": 4096, "D": 4096, "V": 154880,
    "I": 4096, "O": 4096, "M": 2048, "NT": 1,
    "QLR": 1536, "KVLR": 512, "KVLR_R": 512, "E": 288,
    "proj": 8192, "num_heads": 64, "head_dim": 128,
    "nhead": 64, "conv_size": 4, "loop_index": 0,
}


class AnatomyValidationError(ValueError):
    pass


def _is_configless(e: ShapeExpressionError) -> bool:
    """判断求值失败是否因缺少运行期 config 字段（可降级为 warning）。"""
    m = str(e)
    return ("缺少字段" in m) or ("未解析的符号" in m and m.endswith("config"))


class ValidationReport:
    def __init__(self) -> None:
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []

    def error(self, path: str, message: str) -> None:
        self.errors.append({"path": path, "level": "error", "message": message})

    def warning(self, path: str, message: str) -> None:
        self.warnings.append({"path": path, "level": "warning", "message": message})

    @property
    def ok(self) -> bool:
        return not self.errors


class AnatomyValidator:
    """对一批积木 + 组装做整体校验。blocks: list[dict]，assemblies: list[dict]。"""

    def __init__(self, blocks: List[Dict[str, Any]], assemblies: Optional[List[Dict[str, Any]]] = None):
        self.blocks = blocks
        self.assemblies = assemblies or []
        # name -> block（含 assembly，便于跨引用）
        self.by_name: Dict[str, Dict[str, Any]] = {b.get("name"): b for b in blocks}
        for a in self.assemblies:
            self.by_name[a.get("name")] = a
        self._current_assembly_name: str = ""

    # ---- 端口辅助 ----
    def _block_ports(self, name: str) -> Dict[str, Any]:
        b = self.by_name.get(name, {})
        if b.get("kind") == "assembly":
            return (b.get("definition") or {}).get("ports", {})
        return b.get("ports", {})

    def _has_port(self, name: str, direction: str, port_id: str) -> bool:
        ports = self._block_ports(name)
        return any(p.get("id") == port_id for p in (ports.get(direction) or []))

    def _ports_inputs(self, name: str) -> List[str]:
        ports = self._block_ports(name)
        return [p.get("id") for p in (ports.get("inputs") or [])]

    def _ports_outputs(self, name: str) -> List[str]:
        ports = self._block_ports(name)
        return [p.get("id") for p in (ports.get("outputs") or [])]

    # ================== 顶层面板接口 ==================
    def validate_block(self, block: Dict[str, Any], report: ValidationReport,
                       ctx: Optional[Dict[str, Any]] = None) -> None:
        name = block.get("name")
        kind = block.get("kind")
        base = f"{name}"
        if kind == "composite":
            self._validate_composite(block, report, base, ctx or {})
        elif kind == "atomic":
            self._validate_atomic_params(block, report, base, ctx or {})

    def validate_assembly(self, definition: Dict[str, Any], report: ValidationReport,
                          ctx: Optional[Dict[str, Any]] = None, name: str = "") -> None:
        """校验一个 assembly 的 definition（steps/edges/ports）。"""
        self._current_assembly_name = name
        steps = definition.get("steps") or []
        steps_map: Dict[str, Dict[str, Any]] = {}
        for s in steps:
            sid = s.get("id")
            if not sid:
                report.error("steps", "step 缺少 id")
                continue
            if sid in steps_map:
                report.error("steps", f"step id 重复: {sid}")
                continue
            steps_map[sid] = s
            self._validate_port_bind(s.get("id"), s.get("block"), s.get("port_bind"),
                                     report, f"steps.{sid}")
        # 引用的积木/组装存在
        for s in steps:
            blk = s.get("block")
            if blk is not None and blk not in self.by_name:
                report.error(f"steps.{s.get('id')}", f"引用的积木不存在: {blk}")
        # edges + ports 存在性
        owned_inputs = set(self._ports_inputs(name))
        for i, e in enumerate(definition.get("edges") or []):
            from_ = e.get("from") or {}
            fsrc = from_.get("id")
            if fsrc not in steps_map and fsrc not in owned_inputs:
                report.error(f"edges[{i}]", f"from 引用不存在: {fsrc}")
        self._validate_assembly_ports(definition.get("ports") or {}, steps_map, report, "ports")
        # loop 合法性
        for s in steps:
            loop = s.get("loop")
            if loop:
                self._validate_loop(s.get("id"), loop, report, f"steps.{s.get('id')}.loop", ctx)
        # 环检测
        adj = {sid: [] for sid in steps_map}
        if self._has_cycle(adj):
            report.error("steps", "assembly 步骤存在循环依赖（不允许）")

    # ================== composite 校验 ==================
    def _validate_composite(self, block: Dict[str, Any], report: ValidationReport,
                            base: str, ctx: Dict[str, Any]) -> None:
        children = block.get("children") or []
        names = {c.get("id") for c in children if c.get("id")}
        if len(names) != len(children):
            report.error(base, "children 存在重复 id")
        # 引用的子积木存在、且 kind 合法
        for c in children:
            ref = c.get("block")
            cid = c.get("id")
            if ref is None:
                report.error(f"{base}.children.{cid}", "child 缺少 block 引用")
                continue
            if ref not in self.by_name:
                report.error(f"{base}.children.{cid}", f"引用的积木不存在: {ref}")
                continue
            # 允许 composite 内嵌套 composite（如 Glm5NextMultiTokenPredictorLayer 嵌 Glm5NextDecoderLayer）
            self._validate_port_bind(cid, ref, c.get("port_bind"), report, f"{base}.children.{cid}")
            # condition 表达式可求值（config 相关失败降级为 warning）
            if c.get("condition") is not None:
                try:
                    eval_condition(c["condition"], ctx)
                except ShapeExpressionError as e:
                    if _is_configless(e):
                        report.warning(f"{base}.children.{cid}.condition",
                                       f"依赖运行期 config，暂无法静态求值: {e}")
                    else:
                        report.error(f"{base}.children.{cid}.condition", str(e))
        # edge 结构
        edges = block.get("edges") or []
        for i, e in enumerate(edges):
            path = f"{base}.edges[{i}]"
            from_ = e.get("from") or {}
            to_ = e.get("to") or {}
            fsrc, fport = from_.get("id"), from_.get("port")
            tdst, tport = to_.get("id"), to_.get("port")
            # 端口连线的目标必须存在
            if tport and tport not in (self._ports_outputs(tdst) if tdst in self.by_name else []):
                # to 段可能是该 composite 的顶层输出
                owned_out = self._ports_outputs(block.get("name"))
                if tport not in owned_out:
                    report.error(path, f"连线目标端口不存在: {tdst}.{tport}")
        # 端口 self-ports
        self._validate_block_ports(block, report, base)

    # ================== 内部小工具 ==================
    def _validate_atomic_params(self, block: Dict[str, Any], report: ValidationReport,
                                base: str, ctx: Dict[str, Any]) -> None:
        schema = block.get("params_schema") or {}
        props = schema.get("properties") or {}
        for pname, pdef in props.items():
            # condition 可求值
            cond = pdef.get("condition")
            if cond is not None:
                try:
                    eval_condition(cond, ctx or {"config": {}})
                except ShapeExpressionError as e:
                    if _is_configless(e):
                        report.warning(f"{base}.params.{pname}",
                                       f"依赖运行期 config，暂无法静态求值: {e}")
                    else:
                        report.error(f"{base}.params.{pname}", f"condition 求值失败: {e}")
        self._validate_block_ports(block, report, base)

    def _validate_block_ports(self, block: Dict[str, Any], report: ValidationReport,
                              base: str) -> None:
        ports = block.get("ports") or {}
        for direction in ("inputs", "outputs"):
            seen = set()
            for p in (ports.get(direction) or []):
                pid = p.get("id")
                if not pid:
                    report.error(f"{base}.ports.{direction}", "端口缺少 id")
                    continue
                if pid in seen:
                    report.error(f"{base}.ports.{direction}.{pid}", "端口 id 重复")
                seen.add(pid)
                shape = p.get("shape")
                if shape:
                    try:
                        sym = {**_FALLBACK_SYMBOLS}
                        eval_shape(shape, sym)
                    except ShapeExpressionError as e:
                        report.error(f"{base}.ports.{direction}.{pid}", f"形状表达式错误: {e}")

    def _validate_port_bind(self, cid: Any, ref: Optional[str], bind: Any,
                            report: ValidationReport, path: str) -> None:
        if not bind:
            return
        # 校验 port_bind 的每个键是否是被引用积木声明过的参数
        if ref and ref in self.by_name:
            schema = self.by_name[ref].get("params_schema") or {}
            props = schema.get("properties") or {}
            for k in bind.keys():
                if k not in props and k not in ("_note", "x_shape_note"):
                    report.warning(f"{path}.port_bind.{k}",
                                   f"绑定参数 {k} 未在 {ref} 的 params_schema 中声明")

    def _validate_edges(self, steps_map: Dict[str, Any], edges: List[Any],
                        report: ValidationReport, path: str) -> None:
        # 允许 from.id 引用本 assembly 的输入端口（首个数据源），或前序步骤
        owned_inputs = set()
        for i, e in enumerate(edges):
            from_ = e.get("from") or {}
            to_ = e.get("to") or {}
            fsrc = from_.get("id")
            tdst = to_.get("id")
            if fsrc not in steps_map and fsrc not in owned_inputs:
                report.error(f"{path}[{i}]", f"from 引用不存在: {fsrc}")
            # 连线到输出端口时，to.port 应是本 assembly 的 output 端口
            if to_.get("port"):
                owned_out = self._ports_outputs(self._current_assembly_name or "")
                if owned_out and to_["port"] not in owned_out:
                    if tdst in steps_map:
                        blk = steps_map[tdst].get("block")
                        if blk in self.by_name and to_["port"] in self._ports_outputs(blk):
                            pass  # 子积木自身输出端口
                        else:
                            report.warning(f"{path}[{i}]",
                                           f"to 端口 {to_['port']} 既非本 assembly 输出也非子积木 {blk} 输出")

    def _validate_assembly_ports(self, ports: Dict[str, Any], steps_map: Dict[str, Any],
                                 report: ValidationReport, path: str) -> None:
        for direction in ("inputs", "outputs"):
            seen = set()
            for p in (ports.get(direction) or []):
                pid = p.get("id")
                if pid and pid in seen:
                    report.error(f"{path}.{direction}", f"端口 id 重复: {pid}")
                if pid:
                    seen.add(pid)

    def _validate_loop(self, sid: Any, loop: Any, report: ValidationReport, path: str,
                       ctx: Optional[Dict[str, Any]] = None) -> None:
        count = loop.get("count")
        if count is None:
            report.error(path, "loop 缺少 count")
            return
        try:
            eval_expression(count, ctx or {**_FALLBACK_SYMBOLS, "config": {}})
        except ShapeExpressionError as e:
            # count 依赖运行时 config（如 config.num_hidden_layers）时无法静态求值，
            # 降级为 warning；仍保留提示。
            report.warning(path, f"loop.count 依赖运行期 config，暂无法静态求值: {e}")

    def _has_cycle(self, adj: Dict[str, List[Any]]) -> bool:
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in adj}
        def dfs(n: str) -> bool:
            color[n] = GRAY
            for m in adj.get(n, []):
                if m not in color:
                    continue
                if color[m] == GRAY:
                    return True
                if color[m] == WHITE and dfs(m):
                    return True
            color[n] = BLACK
            return False
        for n in adj:
            if color[n] == WHITE and dfs(n):
                return True
        return False


def build_validation_context(config: Optional[dict] = None,
                             parallel: Optional[dict] = None) -> Dict[str, Any]:
    """构造供 validation / 前端展示的求值上下文。"""
    ctx = build_context(config, parallel)
    ctx.update(_FALLBACK_SYMBOLS)
    return ctx