"""CareerLens Analyzer —— 计算与算法层入口。

职责（spec.md §2.6）：文本清洗、技能归一化、匹配打分、LLM 编排与降级。
禁止：鉴权、岗位数据 CRUD、直连数据库。

**本文件只做三件事**：配置日志、挂中间件、注册路由。
任何业务逻辑都不该出现在这里 —— 它一长，就说明该拆到 `service/` 去了。
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.trace import TraceIdMiddleware
from app.routers import health, internal

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

# 横切：traceId 必须在所有路由之前挂上，否则日志拿不到 traceId（spec.md §2.8）
app.add_middleware(TraceIdMiddleware)

app.include_router(health.router)
app.include_router(internal.router, prefix="/internal")
