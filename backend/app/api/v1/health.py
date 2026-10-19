from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_health_checker
from app.services.health import HealthChecker

router = APIRouter(tags=["meta"])


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    postgres: Literal["ok", "down"]
    mongo: Literal["ok", "down"]
    version: str


@router.get(
    "/health",
    operation_id="getHealth",
    summary="Liveness and dependency check",
    response_model=Health,
)
async def get_health(checker: Annotated[HealthChecker, Depends(get_health_checker)]) -> Health:
    report = await checker.check()
    return Health(
        status=report.status,
        postgres=report.postgres,
        mongo=report.mongo,
        version=report.version,
    )
