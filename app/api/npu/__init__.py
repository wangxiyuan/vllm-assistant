"""NPU 算力管理 API 路由

注意：不要在本包做嵌套 include_router（router.include_router(router)）。
FastAPI 0.141 嵌套挂载存在路径解析问题（请求会落入 SPA fallback），
各子域 router 由 main.py 平铺注册（与项目其他 API 一致）：
  - machines.py  -> /api/npu/machines
  - jobs.py      -> /api/npu/jobs
  - services.py  -> /api/npu/services
  - profiles.py  -> /api/npu/profiles
  - tests.py     -> /api/npu/test-cases, /api/npu/test-runs
  - benchmarks.py-> /api/npu/benchmarks
  - overview.py  -> /api/npu/overview
"""
