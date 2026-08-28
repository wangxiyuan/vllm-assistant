"""Glm5 积木 YAML 的加载/序列化。

YAML 为唯一数据源。支持三种 kind：
  - atomic   : 原子积木（params_schema + ports + vllm）
  - composite: 组合积木（children + edges + segments + ports）
  - assembly : 模型组装（steps + edges + ports）

本模块完成 YAML <-> dict 的解析与规范化（含默认值、类型清洗），
不做跨积木引用校验（由 validation 模块负责）。
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List

import yaml

BLOCK_KINDS = ("atomic", "composite")
ASSEMBLY_KIND = "assembly"


class AnatomyYAMLError(ValueError):
    """YAML 格式错误。"""

    def __init__(self, message: str, doc_index: Optional[int] = None):
        self.doc_index = doc_index
        prefix = f"[doc {doc_index}] " if doc_index is not None else ""
        super().__init__(prefix + message)


def parse_yaml(text: str) -> List[Dict[str, Any]]:
    """解析 YAML 文本为文档列表。

    支持单文档（顶层 list 或单对象）与多文档（--- 分隔）。返回 list[dict]。
    """
    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError as e:
        raise AnatomyYAMLError(f"YAML 解析失败: {e}") from e
    result: List[Dict[str, Any]] = []
    for i, doc in enumerate(docs):
        if doc is None:
            continue
        if isinstance(doc, list):
            for item in doc:
                if isinstance(item, dict):
                    result.append(_normalize(item, i))
        elif isinstance(doc, dict):
            result.append(_normalize(doc, i))
    return result


def _normalize(doc: Dict[str, Any], idx: int) -> Dict[str, Any]:
    kind = doc.get("kind")
    if kind not in (BLOCK_KINDS + (ASSEMBLY_KIND,)):
        raise AnatomyYAMLError(f"无效 kind: {kind!r}（应为 atomic/composite/assembly）", idx)
    name = doc.get("name")
    if not name or not isinstance(name, str):
        raise AnatomyYAMLError("缺少 name", idx)
    return doc


def checksum_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_duplicates(docs: List[Dict[str, Any]]) -> List[str]:
    """返回重复的 name（同一批 YAML 内不允许重名）。"""
    from collections import Counter
    dup = [n for n, c in Counter(d.get("name") for d in docs).items() if c > 1]
    return dup


def block_from_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """把 atomic/composite dict 规范化为落库字段 dict。

    顶层实现的平铺字段统一收集：file/weights/ops（实现来源）、edges/segments
    （连接关系）、forward_note/weight_prefix_note/note（补充说明）。历史版本用 vllm
    列承载，现直接平铺到块顶层，无 vllm 嵌套层。
    """
    extra = {}
    for k in (
        "file", "weights", "ops",
        "edges", "segments",
        "forward_note", "weight_prefix_note", "note",
    ):
        if data.get(k):
            extra[k] = data[k]
    return {
        "name": data["name"],
        "kind": data.get("kind", "atomic"),
        "category": data.get("category", "other"),
        "description": data.get("description", ""),
        "formula": data.get("formula", []),
        "params_schema": data.get("params_schema", {}),
        "ports": data.get("ports", {"inputs": [], "outputs": []}),
        "config": data.get("config", {}),
        "children": data.get("children", []),
        "vllm": extra,
        "state": data.get("state", []),
        "tags": data.get("tags", []),
    }


def assembly_from_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """把 assembly dict 规范化为落库字段 dict。"""
    definition = {
        "steps": data.get("steps", []),
        "edges": data.get("edges", []),
        "ports": data.get("ports", {"inputs": [], "outputs": []}),
    }
    # file/formula/notes 等实现字段随 definition 持久化
    for k in ("file", "formula", "forward_note", "weight_prefix_note", "note"):
        if data.get(k):
            definition[k] = data[k]
    return {
        "name": data["name"],
        "kind": "assembly",
        "category": data.get("category", "other"),
        "description": data.get("description", ""),
        "definition": definition,
        "config": data.get("config", {}),
        "tags": data.get("tags", []),
    }