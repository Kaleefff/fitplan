import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response
from pydantic import BaseModel, Field

from app.api.deps import (
    CurrentUser,
    get_body_metrics_service,
    get_current_user,
    get_user_repository,
)
from app.core.errors import VALIDATION_ERROR_RESPONSE, AppError, Error, ErrorCode
from app.domain.constants import WEIGHT_KG_MAX, WEIGHT_KG_MIN
from app.domain.rounding import round_half_up
from app.services.auth import UserRepository
from app.services.body_metrics import MEASURES, BodyMetricsService, MetricsIn, MetricsView

router = APIRouter(prefix="/body-metrics", tags=["body"])

INT_MAX = 2_147_483_647
# column ranges: NUMERIC(5, 2) cm, NUMERIC(4, 2) % (api-rules.md: out of range is 422)
Cm = Annotated[float, Field(gt=0, le=999.99, description="cm")]


class BodyMetricsBody(BaseModel):
    client_uuid: uuid.UUID | None = None
    measured_on: date
    weight: Annotated[float, Field(ge=float(WEIGHT_KG_MIN), le=float(WEIGHT_KG_MAX))]
    chest: Cm | None = None
    waist: Cm | None = None
    thigh: Cm | None = None
    bicep: Cm | None = None
    hip: Cm | None = None
    calf: Cm | None = None
    fat_percentage: Annotated[float, Field(ge=0, le=99.99)] | None = None

    def to_input(self) -> MetricsIn:
        def two_places(value: float | None) -> Decimal | None:
            return None if value is None else round_half_up(Decimal(str(value)), 2)

        return MetricsIn(
            measured_on=self.measured_on,
            **{name: two_places(getattr(self, name)) for name in MEASURES if name != "measured_on"},
        )


class BodyMetricsOut(BaseModel):
    id: int
    client_uuid: uuid.UUID | None
    measured_on: date
    weight: float
    chest: float | None
    waist: float | None
    thigh: float | None
    bicep: float | None
    hip: float | None
    calf: float | None
    fat_percentage: float | None
    recorded_at: datetime

    @classmethod
    def of(cls, m: MetricsView) -> "BodyMetricsOut":
        def number(value: Decimal | None) -> float | None:
            return None if value is None else float(value)

        return cls(
            id=m.id,
            client_uuid=m.client_uuid,
            measured_on=m.measured_on,
            recorded_at=m.recorded_at,
            **{name: number(getattr(m, name)) for name in MEASURES if name != "measured_on"},
        )


def _error(description: str) -> dict:
    return {"model": Error, "description": description}


User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[BodyMetricsService, Depends(get_body_metrics_service)]
UNAUTHORIZED = _error("Missing, expired or invalid token")


@router.get(
    "",
    operation_id="listBodyMetrics",
    summary="Body measurement history, newest first",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED},
)
async def list_body_metrics(
    user: User,
    service: Service,
    date_from: Annotated[
        date | None, Query(alias="from", description="First day, inclusive")
    ] = None,
    date_to: Annotated[date | None, Query(alias="to", description="Last day, inclusive")] = None,
) -> list[BodyMetricsOut]:
    return [BodyMetricsOut.of(m) for m in await service.history(user.id, date_from, date_to)]


@router.post(
    "",
    operation_id="saveBodyMetrics",
    summary="Save the measurement of a day (one per day)",
    status_code=201,
    responses={
        **VALIDATION_ERROR_RESPONSE,
        401: UNAUTHORIZED,
        409: _error("client_uuid of a deleted or foreign row, or the day is taken"),
    },
)
async def save_body_metrics(
    body: BodyMetricsBody,
    user: User,
    service: Service,
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> BodyMetricsOut:
    account = await users.get_by_id(user.id)
    if account is None:
        raise AppError(401, ErrorCode.UNAUTHORIZED, "Unknown user")
    saved = await service.save(
        user.id, body.to_input(), body.client_uuid, account.timezone, datetime.now(UTC)
    )
    return BodyMetricsOut.of(saved)


@router.delete(
    "/{body_metrics_id}",
    operation_id="deleteBodyMetrics",
    summary="Delete a measurement (soft)",
    status_code=204,
    response_class=Response,
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED, 404: _error("No such measurement")},
)
async def delete_body_metrics(
    body_metrics_id: Annotated[int, Path(ge=1, le=INT_MAX)], user: User, service: Service
) -> Response:
    await service.delete(user.id, body_metrics_id)
    return Response(status_code=204)
