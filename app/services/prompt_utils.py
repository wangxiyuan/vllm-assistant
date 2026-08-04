"""
Jinja2 模版渲染工具
"""
import os

from jinja2 import Environment, FileSystemLoader, Undefined


class _SilentUndefined(Undefined):
    def __str__(self):
        return "{{ " + self._undefined_name + " }}"

    def __repr__(self):
        return str(self)


_PROMPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prompts")


def _make_env(subdir: str) -> Environment:
    return Environment(
        loader=FileSystemLoader(os.path.join(_PROMPT_DIR, subdir)),
        undefined=_SilentUndefined,
    )


# 缓存各子目录的 Environment
_env_cache: dict[str, Environment] = {}


def render_prompt(subdir: str, template_name: str, **kwargs) -> str:
    if subdir not in _env_cache:
        _env_cache[subdir] = _make_env(subdir)
    tpl = _env_cache[subdir].get_template(template_name)
    return tpl.render(**kwargs)