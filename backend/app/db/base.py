"""Declarative base shared by every model.

The naming convention reproduces PostgreSQL's default names (table_pkey,
table_col_fkey, table_col_key), so Alembic creates constraints with the same
names as database/init/01_schema.sql did. Single-column CHECKs stay unnamed and
PostgreSQL names them table_col_check, as before. Multi-column CHECKs carry the
name PostgreSQL gave them (table_check, table_check1), because their generated
order is not guaranteed.
"""

from sqlalchemy import MetaData, text
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TIMESTAMP

NAMING_CONVENTION = {
    "pk": "%(table_name)s_pkey",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "uq": "%(table_name)s_%(column_0_N_name)s_key",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
}

# Shared column helpers
TIMESTAMPTZ = TIMESTAMP(timezone=True)
NOW = text("now()")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
