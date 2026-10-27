"""The storage the services use; PostgreSQL in the app, in-memory fakes in tests."""

from dataclasses import dataclass

from app.db.repositories.profiles import SqlProfileReader
from app.db.repositories.refresh_tokens import SqlRefreshTokenRepository
from app.db.repositories.training_plans import SqlTrainingPlanUnitOfWork
from app.db.repositories.users import SqlUserRepository
from app.db.repositories.workouts import SqlWorkoutUnitOfWork
from app.db.session import get_sessionmaker
from app.services.auth import UserRepository
from app.services.nutrition import ProfileReader
from app.services.tokens import RefreshTokenRepository
from app.services.training_plans import TrainingPlanUnitOfWork
from app.services.workouts import WorkoutUnitOfWork


@dataclass(frozen=True)
class Repositories:
    users: UserRepository
    refresh_tokens: RefreshTokenRepository
    profiles: ProfileReader
    workouts: WorkoutUnitOfWork
    training_plans: TrainingPlanUnitOfWork


def sql_repositories() -> Repositories:
    """No connection is opened here; the shared engine connects on first use."""
    sessions = get_sessionmaker()
    return Repositories(
        users=SqlUserRepository(sessions),
        refresh_tokens=SqlRefreshTokenRepository(sessions),
        profiles=SqlProfileReader(sessions),
        workouts=SqlWorkoutUnitOfWork(sessions),
        training_plans=SqlTrainingPlanUnitOfWork(sessions),
    )
