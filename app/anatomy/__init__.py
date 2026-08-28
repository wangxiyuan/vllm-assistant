"""积木式模型拆解引擎（YAML 为唯一数据源）。

包含：
  - shape_engine: 形状/参数/条件表达式求值
  - yaml_loader:  YAML -> dict 解析与规范化
  - validation:   跨积木引用 + 数据流校验
"""
from .shape_engine import (
    ShapeExpressionError, build_context, eval_condition, eval_expression,
    eval_shape, resolve_template,
)
from .validation import (
    AnatomyValidationError, AnatomyValidator, ValidationReport,
    build_validation_context,
)
from .yaml_loader import (
    AnatomyYAMLError, assembly_from_dict, block_from_dict, checksum_of,
    parse_yaml, validate_duplicates,
)

__all__ = [
    "ShapeExpressionError", "build_context", "eval_condition", "eval_expression",
    "eval_shape", "resolve_template",
    "AnatomyValidationError", "AnatomyValidator", "ValidationReport",
    "build_validation_context",
    "AnatomyYAMLError", "assembly_from_dict", "block_from_dict", "checksum_of",
    "parse_yaml", "validate_duplicates",
]