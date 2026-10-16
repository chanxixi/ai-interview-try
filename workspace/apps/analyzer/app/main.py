"""CareerLens Analyzer —— 计算与算法层入口。

职责（spec.md §2.6）：文本清洗、技能归一化、匹配打分、LLM 编排与降级。
禁止：鉴权、岗位数据 CRUD、直连数据库。

**本文件只做三件事**：配置日志、挂中间件、注册路由。
任何业务逻辑都不该出现在这里 —— 它一长，就说明该拆到 `service/` 去了。
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.v1 import health, internal, stream
from app.core.config import settings
from app.core.errors.exception_handlers import register_exception_handlers
from app.core.observability.logging import setup_logging
from app.core.observability.trace import TraceIdMiddleware

setup_logging(settings.log_level)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("analyzer starting (llm_enabled=%s)", settings.llm_enabled)
    yield
    logger.info("analyzer stopped")


app = FastAPI(
    title="CareerLens Analyzer",
    version=settings.version,
    description="文本清洗 / 技能归一化 / 匹配分析（骨架阶段）",
    lifespan=lifespan,
)

# 统一错误收口：所有异常出口都变成 {code, message, traceId}（spec.md §2.3）
register_exception_handlers(app)

# 横切：traceId 必须在所有路由之前挂上，否则日志拿不到 traceId（spec.md §2.8）
app.add_middleware(TraceIdMiddleware)

app.include_router(health.router)
app.include_router(internal.router, prefix="/internal")
# part2 流式入口（spec §2.2）。同样挂 `/internal` 前缀 —— 它是 Java→Python 的内部接口，
# 与同步版 `/internal/analyze` 并列，而不是另起一个对外路径。
app.include_router(stream.router, prefix="/internal")
