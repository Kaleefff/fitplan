from fastapi import APIRouter

from app.api.v1 import (
    account,
    auth,
    body_metrics,
    health,
    nutrition,
    profile,
    reference,
    training_plans,
    workouts,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(nutrition.router)
api_router.include_router(workouts.router)
api_router.include_router(training_plans.router)
api_router.include_router(profile.router)
api_router.include_router(reference.router)
api_router.include_router(account.router)
api_router.include_router(training_plans.sessions_router)
api_router.include_router(body_metrics.router)
