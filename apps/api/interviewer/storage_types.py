from __future__ import annotations

from datetime import UTC, datetime
import math

from sqlalchemy import DateTime, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator, TypeEngine


class UTCDateTime(TypeDecorator[datetime]):
    """Same physical DATETIME/timestamptz; normalize the bind/result boundary."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Persisted application timestamps must include a timezone")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        # SQLite stores UTC without an offset; PostgreSQL returns an aware timestamp.
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class PortableJSON(TypeDecorator[object]):
    """Reject values PostgreSQL JSONB cannot represent, including on SQLite."""
    impl = JSON(none_as_null=True)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[object]:
        from typing import cast
        return cast(TypeEngine[object], dialect.type_descriptor(JSONB(none_as_null=True) if dialect.name == "postgresql" else JSON(none_as_null=True)))

    def process_bind_param(self, value: object, dialect: Dialect) -> object:
        def validate(item: object) -> None:
            if item is None or isinstance(item, (bool, int)):
                return
            if isinstance(item, float) and math.isfinite(item):
                return
            if isinstance(item, str):
                if "\x00" in item:
                    raise ValueError("JSONB does not support zero codepoints")
                item.encode("utf-8", errors="strict")
                return
            if isinstance(item, list):
                for child in item:
                    validate(child)
                return
            if isinstance(item, dict) and all(isinstance(key, str) for key in item):
                for key, child in item.items():
                    validate(key)
                    validate(child)
                return
            raise ValueError("Value is not portable finite JSON")
        validate(value)
        return value
