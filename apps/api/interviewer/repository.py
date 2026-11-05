"""Persistence port for portable SQLAlchemy expressions; raw driver SQL stays in migrations."""
from __future__ import annotations

from typing import Protocol
from collections.abc import Mapping
from uuid import uuid4

from sqlalchemy.engine import Connection
from sqlalchemy.sql import Executable
from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

Row = dict[str, object]


class StorageSession(Protocol):
    def rows(self, statement: Executable) -> list[Row]: ...
    def scalar(self, statement: Executable) -> object: ...
    def exists(self, statement: Executable) -> bool: ...
    def command(self, statement: Executable) -> None: ...
    def insert_if_absent(self, entity: Table, values: Mapping[str, object], unique_columns: list[str]) -> bool: ...


class SQLAlchemyRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def rows(self, statement: Executable) -> list[Row]:
        return [dict(item) for item in self._connection.execute(statement).mappings()]

    def scalar(self, statement: Executable) -> object:
        return self._connection.execute(statement).scalar_one()

    def exists(self, statement: Executable) -> bool:
        return self._connection.execute(statement).first() is not None

    def command(self, statement: Executable) -> None:
        self._connection.execute(statement)

    def insert_if_absent(self, entity: Table, values: Mapping[str, object], unique_columns: list[str]) -> bool:
        values = {"id": str(uuid4()), **values}
        factory = pg_insert if self._connection.dialect.name == "postgresql" else sqlite_insert
        statement = factory(entity).values(**values).on_conflict_do_nothing(index_elements=unique_columns).returning(entity.c.id)
        return self._connection.execute(statement).first() is not None


def repository(session: StorageSession | Connection) -> StorageSession:
    # Frozen migration/constraint tests and offline import retain their explicit raw connection.
    return SQLAlchemyRepository(session) if isinstance(session, Connection) else session
