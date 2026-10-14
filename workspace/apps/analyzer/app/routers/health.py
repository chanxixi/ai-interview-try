"""健康检查：spec.md §2.8 要求每个服务暴露 GET /healthz。"""

from fastapi import APIRouter

from app.config import settings
from app.models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse(service=settings.service_name)
