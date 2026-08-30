"""
Tools 注册入口

每个工具模块被 import 时自动调用 register_tool() 注册到全局注册表。
新增一个 tool 只需要：
1. 新建文件（如 hf_tools.py）
2. 在文件中定义 schema + handler + register_tool()
3. 在此文件中 import 新模块
"""
from . import registry
from . import github_tools
from . import knowledge_tools
from . import code_tools
from . import doc_tools
from . import academic_tools
from . import web_search_tools
from . import write_tools
from . import npu_tools