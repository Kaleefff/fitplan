from datetime import UTC, datetime, time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field

from app.api.deps import (
    CurrentUser,
    get_current_user,
    get_schedule_service,
    get_training_plan_service,
)
from app.api.v1.training_plans import TrainingSessionOut, session_out
from app.core.errors import VALIDATION_ERROR_RESPONSE, Error
from app.services.schedule import (
    REMINDERS_MAX,
    NotificationView,
    ReminderIn,
    ReminderView,
    ScheduleService,
)
from app.services.training_plans import TrainingPlanService

router = APIRouter(tags=["schedule"])

INT_MAX = 2_147_483_647
Weekday = Annotated[int, Field(ge=1, le=7, description="1 = Monday")]


class ReminderBody(BaseModel):
    message_type: Literal["meal_reminder", "training_reminder"]
    day_of_week: Weekday | None = Field(None, description="null = every day")
    time_of_day: time = Field(description="Local wall-clock time of the user, never converted")
    message: Annotated[str, Field(max_length=250)]
    is_enabled: bool = True


class ReminderOut(BaseModel):
    id: int
    message_type: Literal["meal_reminder", "training_reminder"]
    day_of_week: int | None
    time_of_day: time
    message: str
    is_enabled: bool

    @classmethod
    def of(cls, r: ReminderView) -> "ReminderOut":
        return cls(
            id=r.id,
            message_type=r.message_type,
            day_of_week=r.day_of_week,
            time_of_day=r.time_of_day,
            message=r.message,
            is_enabled=r.is_enabled,
        )


class TrainingSessionPatch(BaseModel):
    day_of_week: Weekday


class NotificationOut(BaseModel):
    id: int
    message_type: Literal[
        "meal_reminder", "training_reminder", "progress_update", "achievement", "motivational"
    ]
    scheduled_at: datetime
    message: str
    data: dict | None
    is_sent: bool
    sent_at: datetime | None
    is_dismissed: bool

    @classmethod
    def of(cls, n: NotificationView) -> "NotificationOut":
        return cls(**n.__dict__)


class NotificationPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[NotificationOut]


def _error(description: str) -> dict:
    return {"model": Error, "description": description}


User = Annotated[CurrentUser, Depends(get_current_user)]
Schedule = Annotated[ScheduleService, Depends(get_schedule_service)]
UNAUTHORIZED = _error("Missing, expired or invalid token")


@router.get(
    "/reminders",
    operation_id="listReminders",
    summary="Training and meal reminders (FR-P9)",
    responses={401: UNAUTHORIZED},
)
async def list_reminders(user: User, service: Schedule) -> list[ReminderOut]:
    return [ReminderOut.of(r) for r in await service.reminders(user.id)]


@router.put(
    "/reminders",
    operation_id="putReminders",
    summary="Replace all reminders",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED},
)
async def put_reminders(
    body: Annotated[list[ReminderBody], Field(max_length=REMINDERS_MAX)],
    user: User,
    service: Schedule,
) -> list[ReminderOut]:
    reminders = [
        ReminderIn(r.message_type, r.day_of_week, r.time_of_day, r.message, r.is_enabled)
        for r in body
    ]
    return [ReminderOut.of(r) for r in await service.replace_reminders(user.id, reminders)]


@router.patch(
    "/training-sessions/{training_session_id}",
    operation_id="updateTrainingSession",
    summary="Move a session to another weekday (FR-P9)",
    responses={
        **VALIDATION_ERROR_RESPONSE,
        401: UNAUTHORIZED,
        404: _error("No such session of the user"),
        409: _error("The weekday is taken in the plan, or the plan is archived"),
    },
)
async def update_training_session(
    training_session_id: Annotated[int, Path(ge=1, le=INT_MAX)],
    body: TrainingSessionPatch,
    user: User,
    plans: Annotated[TrainingPlanService, Depends(get_training_plan_service)],
) -> TrainingSessionOut:
    moved = await plans.move_session(user.id, training_session_id, body.day_of_week)
    return session_out(moved)


@router.get(
    "/notifications",
    operation_id="listNotifications",
    summary="The user's notifications, such as weekly reports and records (FR-P9, FR-R7)",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED},
)
async def list_notifications(
    user: User,
    service: Schedule,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=INT_MAX)] = 0,
) -> NotificationPage:
    total, items = await service.notifications(user.id, datetime.now(UTC), limit, offset)
    return NotificationPage(
        total=total, limit=limit, offset=offset, items=[NotificationOut.of(n) for n in items]
    )
