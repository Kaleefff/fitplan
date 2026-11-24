"""Progress reports and their export (B-25, S-04; FR-R1, FR-R5, FR-R6; api-rules.md
"Reports and notifications")."""

from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Response
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, get_current_user, get_report_service, get_user_repository
from app.api.v1.analytics import KeyLiftOut, _timezone
from app.core.errors import VALIDATION_ERROR_RESPONSE, Error
from app.domain.constants import ReportType
from app.services.auth import UserRepository
from app.services.report_export import to_csv, to_pdf
from app.services.reports import ReportService, ReportView

router = APIRouter(prefix="/reports", tags=["analytics"])

INT_MAX = 2_147_483_647
User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[ReportService, Depends(get_report_service)]
Users = Annotated[UserRepository, Depends(get_user_repository)]
UNAUTHORIZED = {"model": Error, "description": "Missing, expired or invalid token"}


class GenerateReportBody(BaseModel):
    period_start: date
    period_end: date = Field(description="Inclusive, not before period_start")


class ReportOut(BaseModel):
    id: int
    report_type: ReportType
    report_period_start: date
    report_period_end: date
    weight_difference: float | None
    training_volume: float
    training_sessions_completed: int
    training_sessions_planned: int
    workout_compliance_pct: float | None
    diet_compliance_pct: float | None
    avg_cals_daily: int | None
    key_lifts: list[KeyLiftOut]
    estimated_goal_completion_date: date | None
    irregular_data: bool
    is_auto: bool
    generated_at: datetime

    @classmethod
    def of(cls, report: ReportView) -> "ReportOut":
        f = report.figures

        def number(value) -> float | None:
            return None if value is None else float(value)

        return cls(
            id=report.id,
            report_type=f.report_type,
            report_period_start=f.period_start,
            report_period_end=f.period_end,
            weight_difference=number(f.weight_difference),
            training_volume=float(f.training_volume),
            training_sessions_completed=f.training_sessions_completed,
            training_sessions_planned=f.training_sessions_planned,
            workout_compliance_pct=number(f.workout_compliance_pct),
            diet_compliance_pct=number(f.diet_compliance_pct),
            avg_cals_daily=f.avg_cals_daily,
            key_lifts=[
                KeyLiftOut(
                    exercise_id=k.exercise_id,
                    exercise_name=k.exercise_name,
                    first_e1rm=float(k.first_e1rm),
                    best_e1rm=float(k.best_e1rm),
                )
                for k in f.key_lifts
            ],
            estimated_goal_completion_date=f.estimated_goal_completion_date,
            irregular_data=f.irregular_data,
            is_auto=report.is_auto,
            generated_at=report.generated_at,
        )


class ReportPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ReportOut]


@router.get(
    "",
    operation_id="listReports",
    summary="Stored progress reports (FR-R1, FR-R7)",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED},
)
async def list_reports(
    user: User,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=INT_MAX)] = 0,
) -> ReportPage:
    total, reports = await service.list_reports(user.id, limit, offset)
    return ReportPage(
        total=total, limit=limit, offset=offset, items=[ReportOut.of(r) for r in reports]
    )


@router.post(
    "",
    operation_id="generateReport",
    summary="Generate the progress report of a period (FR-R1)",
    status_code=201,
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED},
)
async def generate_report(
    body: GenerateReportBody, user: User, service: Service, users: Users
) -> ReportOut:
    timezone = await _timezone(users, user.id)
    report = await service.generate(
        user.id, body.period_start, body.period_end, timezone, datetime.now(UTC)
    )
    return ReportOut.of(report)


@router.get(
    "/{report_id}",
    operation_id="getReport",
    summary="Report detail",
    responses={
        **VALIDATION_ERROR_RESPONSE,
        401: UNAUTHORIZED,
        404: {"model": Error, "description": "No such report of the user"},
    },
)
async def get_report(
    report_id: Annotated[int, Path(ge=1, le=INT_MAX)], user: User, service: Service
) -> ReportOut:
    return ReportOut.of(await service.get(user.id, report_id))


EXPORTS = {
    "pdf": ("application/pdf", to_pdf),
    "csv": ("text/csv; charset=utf-8", to_csv),
}


@router.get(
    "/{report_id}/export",
    operation_id="exportReport",
    summary="Export a report to PDF or CSV (FR-R6)",
    response_class=Response,
    responses={
        200: {
            "description": "The file",
            "content": {
                "application/pdf": {
                    "schema": {"type": "string", "contentMediaType": "application/pdf"}
                },
                "text/csv": {"schema": {"type": "string"}},
            },
        },
        **VALIDATION_ERROR_RESPONSE,
        401: UNAUTHORIZED,
        404: {"model": Error, "description": "No such report of the user"},
    },
)
async def export_report(
    report_id: Annotated[int, Path(ge=1, le=INT_MAX)],
    format: Annotated[Literal["pdf", "csv"], Query()],
    user: User,
    service: Service,
) -> Response:
    """The figures of `GET /reports/{id}`: CSV `section,key,value` with a BOM, or a PDF
    with an embedded Unicode font (api-rules.md)."""
    report = ReportOut.of(await service.get(user.id, report_id)).model_dump(mode="json")
    media_type, build = EXPORTS[format]
    filename = f"fitplan-report-{report['report_period_start']}-{report_id}.{format}"
    return Response(
        build(report),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
