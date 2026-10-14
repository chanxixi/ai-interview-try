"""CareerLens Analyzer —— 计算与算法层入口。

职责（spec.md §2.6）：文本清洗、技能归一化、匹配打分、LLM 编排与降级。
禁止：鉴权、岗位数据 CRUD。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.logging_setup import setup_logging
from app.routers import health, internal

setup_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_: FastAPI):
    import logging

    logging.getLogger(__name__).info(
        "analyzer starting (llm_enabled=%s)", settings.llm_enabled
    )
    yield
    logging.getLogger(__name__).info("analyzer stopped")


app = FastAPI(
    title="CareerLens Analyzer",
    version=settings.version,
    description="文本清洗 / 技能归一化 / 匹配分析（骨架阶段）",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(internal.router, prefix="/internal")
