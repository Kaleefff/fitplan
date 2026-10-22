"""In-memory stand-ins for DATA's repositories until DB-01 lands."""

import dataclasses
import uuid
from datetime import datetime

from app.services.tokens import RefreshTokenRecord


class InMemoryRefreshTokenRepository:
    def __init__(self) -> None:
        self.rows: dict[int, RefreshTokenRecord] = {}
        self.replace_conflict = False  # simulates a concurrent refresh that won the race

    async def add(
        self,
        *,
        user_id: int,
        family_id: uuid.UUID,
        token_hash: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> RefreshTokenRecord:
        record = RefreshTokenRecord(
            id=len(self.rows) + 1,
            user_id=user_id,
            family_id=family_id,
            token_hash=token_hash,
            issued_at=issued_at,
            expires_at=expires_at,
            revoked_at=None,
            replaced_by_id=None,
        )
        self.rows[record.id] = record
        return record

    async def get_by_hash(self, token_hash: str) -> RefreshTokenRecord | None:
        return next((row for row in self.rows.values() if row.token_hash == token_hash), None)

    async def replace(self, token_id: int, *, replaced_by_id: int, revoked_at: datetime) -> bool:
        row = self.rows[token_id]
        if self.replace_conflict or row.revoked_at is not None:
            return False
        self.rows[token_id] = dataclasses.replace(
            row, revoked_at=revoked_at, replaced_by_id=replaced_by_id
        )
        return True

    async def revoke_family(self, family_id: uuid.UUID, revoked_at: datetime) -> None:
        self._revoke(lambda row: row.family_id == family_id, revoked_at)

    async def revoke_user(self, user_id: int, revoked_at: datetime) -> None:
        self._revoke(lambda row: row.user_id == user_id, revoked_at)

    def _revoke(self, match, revoked_at: datetime) -> None:
        for row_id, row in self.rows.items():
            if match(row) and row.revoked_at is None:
                self.rows[row_id] = dataclasses.replace(row, revoked_at=revoked_at)

    def live(self) -> list[RefreshTokenRecord]:
        return [row for row in self.rows.values() if row.revoked_at is None]
