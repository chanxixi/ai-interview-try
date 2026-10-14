"""依赖装配 —— FastAPI 的「组合根」。

FastAPI 没有 Spring 那样的自动装配，`Depends` 只负责「调用一个工厂」。
因此**全项目唯一装配具体实现的地方就是这里**（对应 BFF 的 `container.ts`、
Java 的构造器注入）。这样做的好处：

- 换实现只改本文件一处，不用翻遍 router；
- 测试里用 `app.dependency_overrides[get_analysis_service] = lambda: fake`
  即可替换，无需 monkeypatch 模块内部。
"""

from functools import lru_cache

from app.service.analysis_service import AnalysisService, create_analysis_service


@lru_cache
def get_analysis_service() -> AnalysisService:
    """分析服务单例。

    `lru_cache` = 进程级单例（FastAPI 每次请求都会调用工厂，不加缓存会反复构造）。
    测试需要重置时调用 `get_analysis_service.cache_clear()`，或优先使用
    `app.dependency_overrides`。
    """
    return create_analysis_service()
