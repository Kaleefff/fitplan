from fastapi import Request

from app.services.health import HealthChecker


def get_health_checker(request: Request) -> HealthChecker:
    return request.app.state.health_checker
