"""Small, strict shared storage contracts; no agent or provider dependencies."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import secrets
import time
from typing import Annotated, Literal
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, AfterValidator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")

    def canonical_bytes(self) -> bytes:
        return canonical(type(self).model_validate(self).model_dump(mode="json"))


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def nonblank(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(unicodedata.category(c) in {"Cc", "Cs"} for c in value):
        raise ValueError("nonblank UTF-8 text without control characters required")
    return value


Text = Annotated[str, AfterValidator(nonblank)]


def id_type(prefix: str):
    return Annotated[str, Field(pattern=rf"^{prefix}_[0-7][0-9A-HJKMNP-TV-Z]{{25}}$", min_length=len(prefix)+27, max_length=len(prefix)+27)]


def new_id(prefix: str) -> str:
    """ULID binary layout, encoded in Crockford base32; not monotonic within ms."""
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    stamp = time.time_ns() // 1_000_000
    if not 0 <= stamp < 2**48:
        raise ValueError("clock outside ULID timestamp range")
    value = (stamp << 80) | secrets.randbits(80)
    return prefix + "_" + "".join(alphabet[(value >> shift) & 31] for shift in range(125, -1, -5))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TemporalValue(Contract):
    value: Text
    precision: Literal["datetime", "date", "month"]

    @model_validator(mode="after")
    def valid_time(self):
        try:
            self.bounds()
        except OverflowError as error:
            raise ValueError("time interval exceeds supported UTC range") from error
        return self

    def bounds(self) -> tuple[str, str]:
        if self.precision == "datetime":
            parsed = datetime.fromisoformat(self.value)
            if parsed.tzinfo is None or "T" not in self.value:
                raise ValueError("datetime must have an explicit timezone")
            lower = upper = parsed.astimezone(timezone.utc)
        else:
            if self.precision == "month":
                if len(self.value) != 7:
                    raise ValueError("month must be YYYY-MM")
                start = date.fromisoformat(self.value + "-01")
                end = date(start.year, start.month, calendar.monthrange(start.year, start.month)[1]) + timedelta(days=1)
            else:
                if len(self.value) != 10:
                    raise ValueError("date must be YYYY-MM-DD")
                start = date.fromisoformat(self.value)
                end = start + timedelta(days=1)
            lower = datetime.combine(start, datetime.min.time(), timezone(timedelta(hours=14))).astimezone(timezone.utc)
            upper = datetime.combine(end, datetime.min.time(), timezone(timedelta(hours=-12))).astimezone(timezone.utc)
        return lower.isoformat(), upper.isoformat()


class SourceTime(Contract):
    value: TemporalValue | None
    basis: Text | None
    unknown_reason: Literal["not_disclosed_by_source", "not_processed", "not_applicable", "conflict"] | None

    @model_validator(mode="after")
    def explained(self):
        if self.value is None:
            if self.unknown_reason is None:
                raise ValueError("unknown time requires an explicit reason")
        elif self.basis is None or self.unknown_reason is not None:
            raise ValueError("known time requires basis and no unknown reason")
        return self


class FiscalPeriod(Contract):
    label: Text | None
    fiscal_year: Annotated[int, Field(ge=1, le=9999)] | None
    fiscal_quarter: Annotated[int, Field(ge=1, le=4)] | None
    start: date | None
    end: date | None
    basis: Literal["source", "derived_from_fiscal_year_end", "unknown"]

    @model_validator(mode="after")
    def interval(self):
        if self.start and self.end and self.end < self.start:
            raise ValueError("fiscal period end precedes start")
        return self


class CatalogView(Contract):
    catalog_id: id_type("cat")
    revision: Annotated[int, Field(ge=0)]
    token: id_type("rev")


class CatalogError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")
