#!/usr/bin/env python3
"""
数据库初始化脚本 —— 为空数据库填充预置数据。

用法:
    python scripts/init_db.py            # 仅在表为空时写入
    python scripts/init_db.py --force    # 跳过空检查，强制写入（重复 name 会跳过）

写入内容:
    - 8 个算子分类 (OperatorCategory)
    - 12 个预置算子 (Operator)
    - 5 个模型架构分类（仅打印提示，模型分类无独立表）

请在服务首次部署或重置数据库后手动执行。
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# 把项目根目录加入 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models import Operator, OperatorCategory

# ── 预置算子分类 ──
PRESET_CATEGORIES = [
    {"name": "embedding", "display_name": "Embedding", "description": "Token embedding layers", "sort_order": 1},
    {"name": "normalization", "display_name": "Normalization", "description": "Layer normalization", "sort_order": 2},
    {"name": "attention", "display_name": "Attention", "description": "Attention mechanisms", "sort_order": 3},
    {"name": "mlp", "display_name": "MLP", "description": "Multi-Layer Perceptron", "sort_order": 4},
    {"name": "activation", "display_name": "Activation", "description": "Activation functions", "sort_order": 5},
    {"name": "positional", "display_name": "Positional Encoding", "description": "Positional embeddings", "sort_order": 6},
    {"name": "pooling", "display_name": "Pooling", "description": "Pooling layers", "sort_order": 7},
    {"name": "other", "display_name": "Other", "description": "Other layers", "sort_order": 99},
]

# ── 预置算子 ──
PRESET_OPERATORS = [
    # Embedding
    {"name": "Embedding", "display_name": "Embedding", "description": "Token embedding layer that maps input tokens to dense vectors", "category": "embedding", "params_schema": {"type": "object", "properties": {"vocab_size": {"type": "integer", "default": 32000, "description": "Vocabulary size"}, "hidden_size": {"type": "integer", "default": 4096, "description": "Embedding dimension"}}, "required": ["vocab_size", "hidden_size"]}, "input_shape_desc": "(batch_size, seq_len)", "output_shape_desc": "(batch_size, seq_len, hidden_size)"},
    # Normalization
    {"name": "RMSNorm", "display_name": "RMS 归一化", "description": "Root Mean Square Layer Normalization", "category": "normalization", "params_schema": {"type": "object", "properties": {"hidden_size": {"type": "integer", "default": 4096, "description": "Hidden size"}, "eps": {"type": "number", "default": 1e-6, "description": "Epsilon for numerical stability"}}, "required": ["hidden_size"]}, "input_shape_desc": "(batch_size, seq_len, hidden_size)", "output_shape_desc": "(batch_size, seq_len, hidden_size)"},
    {"name": "LayerNorm", "display_name": "Layer 归一化", "description": "Layer Normalization", "category": "normalization", "params_schema": {"type": "object", "properties": {"hidden_size": {"type": "integer", "default": 4096}, "eps": {"type": "number", "default": 1e-5}}, "required": ["hidden_size"]}, "input_shape_desc": "(batch_size, seq_len, hidden_size)", "output_shape_desc": "(batch_size, seq_len, hidden_size)"},
    # Attention
    {"name": "MultiHeadAttention", "display_name": "多头注意力", "description": "Multi-Head Attention (MHA)", "category": "attention", "params_schema": {"type": "object", "properties": {"hidden_size": {"type": "integer", "default": 4096}, "num_heads": {"type": "integer", "default": 32}, "num_kv_heads": {"type": "integer", "default": 32}, "head_dim": {"type": "integer", "default": 128}}, "required": ["hidden_size", "num_heads"]}, "input_shape_desc": "(batch_size, seq_len, hidden_size)", "output_shape_desc": "(batch_size, seq_len, hidden_size)"},
    {"name": "GroupedQueryAttention", "display_name": "分组查询注意力", "description": "Grouped-Query Attention (GQA)", "category": "attention", "params_schema": {"type": "object", "properties": {"hidden_size": {"type": "integer", "default": 4096}, "num_heads": {"type": "integer", "default": 32}, "num_kv_heads": {"type": "integer", "default": 8}, "head_dim": {"type": "integer", "default": 128}}, "required": ["hidden_size", "num_heads", "num_kv_heads"]}, "input_shape_desc": "(batch_size, seq_len, hidden_size)", "output_shape_desc": "(batch_size, seq_len, hidden_size)"},
    {"name": "MLA", "display_name": "多头潜注意力", "description": "Multi-head Latent Attention (MLA), used in DeepSeek series", "category": "attention", "params_schema": {"type": "object", "properties": {"hidden_size": {"type": "integer", "default": 7168}, "num_heads": {"type": "integer", "default": 128}, "kv_lora_rank": {"type": "integer", "default": 512}, "qk_rope_head_dim": {"type": "integer", "default": 64}}, "required": ["hidden_size", "num_heads"]}, "input_shape_desc": "(batch_size, seq_len, hidden_size)", "output_shape_desc": "(batch_size, seq_len, hidden_size)"},
    # MLP
    {"name": "MLP", "display_name": "MLP", "description": "Multi-Layer Perceptron (SwiGLU)", "category": "mlp", "params_schema": {"type": "object", "properties": {"hidden_size": {"type": "integer", "default": 4096}, "intermediate_size": {"type": "integer", "default": 11008}, "activation": {"type": "string", "default": "silu", "enum": ["silu", "gelu", "relu"]}}, "required": ["hidden_size", "intermediate_size"]}, "input_shape_desc": "(batch_size, seq_len, hidden_size)", "output_shape_desc": "(batch_size, seq_len, hidden_size)"},
    {"name": "MoE", "display_name": "混合专家", "description": "Mixture of Experts layer with router", "category": "mlp", "params_schema": {"type": "object", "properties": {"hidden_size": {"type": "integer", "default": 7168}, "intermediate_size": {"type": "integer", "default": 2048}, "num_experts": {"type": "integer", "default": 256}, "num_experts_per_tok": {"type": "integer", "default": 8}}, "required": ["hidden_size", "num_experts"]}, "input_shape_desc": "(batch_size, seq_len, hidden_size)", "output_shape_desc": "(batch_size, seq_len, hidden_size)"},
    # Positional
    {"name": "RotaryEmbedding", "display_name": "RoPE", "description": "Rotary Position Embedding", "category": "positional", "params_schema": {"type": "object", "properties": {"dim": {"type": "integer", "default": 128}, "max_position_embeddings": {"type": "integer", "default": 131072}, "theta": {"type": "number", "default": 10000}}, "required": ["dim"]}, "input_shape_desc": "position_ids: (batch_size, seq_len)", "output_shape_desc": "cos/sin: (seq_len, dim)"},
    # Output
    {"name": "Linear", "display_name": "线性层", "description": "Linear projection layer", "category": "other", "params_schema": {"type": "object", "properties": {"in_features": {"type": "integer", "default": 4096}, "out_features": {"type": "integer", "default": 32000}, "bias": {"type": "boolean", "default": False}}, "required": ["in_features", "out_features"]}, "input_shape_desc": "(..., in_features)", "output_shape_desc": "(..., out_features)"},
    {"name": "LMHead", "display_name": "LM Head", "description": "Language model head (projection to vocabulary)", "category": "other", "params_schema": {"type": "object", "properties": {"hidden_size": {"type": "integer", "default": 4096}, "vocab_size": {"type": "integer", "default": 32000}}, "required": ["hidden_size", "vocab_size"]}, "input_shape_desc": "(batch_size, seq_len, hidden_size)", "output_shape_desc": "(batch_size, seq_len, vocab_size)"},
    # Activation
    {"name": "SiLU", "display_name": "SiLU", "description": "Sigmoid Linear Unit activation", "category": "activation", "params_schema": {"type": "object", "properties": {}}, "input_shape_desc": "(...) in_features", "output_shape_desc": "(...) in_features"},
]

# ── 模型架构分类（前端硬编码，此处仅做记录） ──
PRESET_MODEL_CATEGORIES = [
    {"name": "dense", "display_name": "Dense", "description": "Dense Transformer (e.g. LLaMA, Qwen, Mistral)"},
    {"name": "moe", "display_name": "MoE", "description": "Mixture of Experts (e.g. DeepSeek V2/V3, Mixtral)"},
    {"name": "hybrid", "display_name": "Hybrid", "description": "Hybrid dense + MoE (e.g. DeepSeek V4, Qwen3 MoE)"},
    {"name": "state_space", "display_name": "State Space", "description": "State space models (e.g. Mamba)"},
    {"name": "other", "display_name": "Other", "description": "Other architectures"},
]


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def seed(force: bool = False):
    db = SessionLocal()
    try:
        # ── 分类 ──
        existing_cats = db.query(OperatorCategory).count()
        if existing_cats > 0 and not force:
            print(f"[skip] OperatorCategory 已有 {existing_cats} 条，跳过分类写入（--force 可强制）")
        else:
            added = 0
            for cat_data in PRESET_CATEGORIES:
                exists = db.query(OperatorCategory).filter_by(name=cat_data["name"]).first()
                if exists:
                    continue
                db.add(OperatorCategory(
                    name=cat_data["name"],
                    display_name=cat_data["display_name"],
                    description=cat_data.get("description", ""),
                    sort_order=cat_data.get("sort_order", 0),
                    created_at=_now(),
                    updated_at=_now(),
                ))
                added += 1
            db.commit()
            print(f"[ok] OperatorCategory: 写入 {added} 条（共 {len(PRESET_CATEGORIES)} 个预置分类）")

        # ── 算子 ──
        existing_ops = db.query(Operator).count()
        if existing_ops > 0 and not force:
            print(f"[skip] Operator 已有 {existing_ops} 条，跳过算子写入（--force 可强制）")
        else:
            added = 0
            for op_data in PRESET_OPERATORS:
                exists = db.query(Operator).filter_by(name=op_data["name"]).first()
                if exists:
                    continue
                db.add(Operator(
                    name=op_data["name"],
                    display_name=op_data["display_name"],
                    description=op_data.get("description", ""),
                    category=op_data.get("category", "other"),
                    params_schema=json.dumps(op_data.get("params_schema", {}), ensure_ascii=False),
                    input_shape_desc=op_data.get("input_shape_desc", ""),
                    output_shape_desc=op_data.get("output_shape_desc", ""),
                    tags=json.dumps([], ensure_ascii=False),
                    created_at=_now(),
                    updated_at=_now(),
                ))
                added += 1
            db.commit()
            print(f"[ok] Operator: 写入 {added} 条（共 {len(PRESET_OPERATORS)} 个预置算子）")

        # ── 模型分类提示 ──
        print(f"[info] 模型架构分类（{len(PRESET_MODEL_CATEGORIES)} 个）由前端硬编码，无需写入数据库: "
              + ", ".join(c["name"] for c in PRESET_MODEL_CATEGORIES))

        print("\n[done] 数据库初始化完成。")
    except Exception as e:
        db.rollback()
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    force = "--force" in sys.argv
    if force:
        print("[warn] --force 模式：跳过空检查，重复 name 将被跳过")
    seed(force=force)
