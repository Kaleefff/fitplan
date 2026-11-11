"""Today's date as the app sees it for a user with the default time zone."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

DEFAULT_TZ = ZoneInfo("Europe/Warsaw")


def today() -> date:
    return datetime.now(DEFAULT_TZ).date()
