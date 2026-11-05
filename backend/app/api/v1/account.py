from datetime import date
from typing import Annotated
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, Response
from pydantic import AfterValidator, BaseModel, EmailStr, Field, model_validator

from app.api.deps import CurrentUser, auth_rate_limit, get_account_service, get_current_user
from app.api.v1.auth import Email, NewPassword, PersonName
from app.core.errors import VALIDATION_ERROR_RESPONSE, Error
from app.db.repositories.users import UserRecord
from app.services.account import AccountService

router = APIRouter(prefix="/users/me", tags=["account"])


def _iana(name: str) -> str:
    if name not in available_timezones():
        raise ValueError("Unknown IANA time zone, for example Europe/Warsaw")
    return name


TimeZone = Annotated[str, AfterValidator(_iana)]


class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: str
    surname: str
    timezone: str
    registration_date: date

    @classmethod
    def of(cls, user: UserRecord) -> "UserOut":
        return cls(
            id=user.id,
            email=user.email,
            name=user.name,
            surname=user.surname,
            timezone=user.timezone,
            registration_date=user.registration_date,
        )


class UserPatchBody(BaseModel):
    """At least one field; a field that is sent may not be null."""

    # not Optional: an absent field stays None, a null is a type error on that field
    name: PersonName = Field(default=None)
    surname: PersonName = Field(default=None)
    timezone: TimeZone = Field(default=None)

    @model_validator(mode="after")
    def _some_field(self) -> "UserPatchBody":
        if not self.model_fields_set:
            raise ValueError("Send at least one field")
        return self


class ChangeEmailBody(BaseModel):
    new_email: Email
    current_password: str


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: NewPassword


class DeleteAccountBody(BaseModel):
    password: str | None = None


def _error(description: str) -> dict:
    return {"model": Error, "description": description}


User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[AccountService, Depends(get_account_service)]
UNAUTHORIZED = _error("Missing, expired or invalid token")
WRONG_PASSWORD = _error("Wrong current password (code invalid_credentials)")
LIMITED = _error("Too many requests")


@router.get("", operation_id="getMe", summary="Current user", responses={401: UNAUTHORIZED})
async def get_me(user: User, service: Service) -> UserOut:
    return UserOut.of(await service.get(user.id))


@router.patch(
    "",
    operation_id="updateMe",
    summary="Change name, surname or time zone (FR-U4)",
    responses={**VALIDATION_ERROR_RESPONSE, 401: UNAUTHORIZED},
)
async def update_me(body: UserPatchBody, user: User, service: Service) -> UserOut:
    fields = {f: getattr(body, f) for f in body.model_fields_set}
    return UserOut.of(await service.update(user.id, fields))


@router.post(
    "/email",
    operation_id="changeEmail",
    summary="Change email, current password required (FR-U4)",
    dependencies=[Depends(auth_rate_limit)],
    responses={
        **VALIDATION_ERROR_RESPONSE,
        401: WRONG_PASSWORD,
        409: _error("Email already registered"),
        429: LIMITED,
    },
)
async def change_email(body: ChangeEmailBody, user: User, service: Service) -> UserOut:
    return UserOut.of(await service.change_email(user.id, body.new_email, body.current_password))


@router.post(
    "/password",
    operation_id="changePassword",
    summary="Change password, current password required (FR-U4)",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(auth_rate_limit)],
    responses={**VALIDATION_ERROR_RESPONSE, 401: WRONG_PASSWORD, 429: LIMITED},
)
async def change_password(body: ChangePasswordBody, user: User, service: Service) -> Response:
    await service.change_password(user.id, body.current_password, body.new_password)
    return Response(status_code=204)


@router.post(
    "/delete",
    operation_id="deleteAccount",
    summary="Delete the account and all related data (FR-U5, GDPR)",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(auth_rate_limit)],
    responses={**VALIDATION_ERROR_RESPONSE, 401: WRONG_PASSWORD, 429: LIMITED},
)
async def delete_account(body: DeleteAccountBody, user: User, service: Service) -> Response:
    await service.delete(user.id, body.password)
    return Response(status_code=204)
