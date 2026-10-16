"""依赖装配 —— FastAPI 的「组合根」。

FastAPI 没有 Spring 那样的自动装配，`Depends` 只负责「调用一个工厂」。
因此**全项目唯一装配具体实现的地方就是这里**（对应 BFF 的 `container.ts`、
Java 的构造器注入）。这样做的好处：

- 换实现只改本文件一处，不用翻遍 router；
- 测试里用 `app.dependency_overrides[get_analysis_service] = lambda: fake`
  即可替换，无需 monkeypatch 模块内部。
"""

from functools import lru_cache
from app.llm.events import LlmClient
from app.llm.client import create_llm_client

from app.service.orchestration.analysis_service import AnalysisService, create_analysis_service
from app.service.skill.normalizer import SkillDictionary, get_dictionary as _load_dictionary


@lru_cache
def get_analysis_service() -> AnalysisService:
    """分析服务单例。

    `lru_cache` = 进程级单例（FastAPI 每次请求都会调用工厂，不加缓存会反复构造）。
    测试需要重置时调用 `get_analysis_service.cache_clear()`，或优先使用
    `app.dependency_overrides`。
    """
    return create_analysis_service()


@lru_cache
def get_dictionary() -> SkillDictionary:
    """技能词典单例。

    与 `get_analysis_service` 分开而不是塞进它里面：词典同时被**同步**分析
    和**流式**分析两条链路使用，而 `create_analysis_service()` 目前不接收依赖。
    真到需要注入的那天，改这一个函数即可。
    """
    return _load_dictionary()


@lru_cache
def get_llm_client() -> LlmClient:
    """LLM 客户端单例。

    内部持有一个可复用的 `httpx.AsyncClient` 会更省，但那会让「客户端生命周期」
    和「FastAPI 应用生命周期」纠缠在一起。当前每次流式请求自建自销，
    代价是一次 TCP 握手 —— 对一个 3h 项目来说，可预测比省一次握手重要。
    """
    return create_llm_client()
