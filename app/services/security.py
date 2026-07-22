"""
安全模块
对应 DESIGN-ARTICLES.md 10.1 路径遍历防护
"""
from pathlib import Path


def get_safe_repo_path(base_path: str, repo_name: str, file_path: str) -> Path:
    """
    确保文件路径在仓库范围内，防止路径遍历攻击。

    Args:
        base_path: 仓库根目录（如 data/repos）
        repo_name: 仓库名（如 vllm）
        file_path: 用户提供的文件相对路径

    Returns:
        安全的绝对路径
    """
    base = Path(base_path).resolve()
    target = (base / repo_name / file_path).resolve()

    if not target.is_relative_to(base / repo_name):
        raise ValueError(f"Path traversal detected: {repo_name}/{file_path}")

    return target