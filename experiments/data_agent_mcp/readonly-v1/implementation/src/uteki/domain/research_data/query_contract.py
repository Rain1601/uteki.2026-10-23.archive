"""Versioned contracts for the local, candidate-aware query pilot."""
from __future__ import annotations

from datetime import date
from calendar import monthrange
from decimal import Context, Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

VERSION = "research-query-v0.3"
SOURCE_PERIOD_VERSION = "research-query-v0.4"
EXACT_SOURCE_PERIOD_VERSION = "research-query-v0.5"
SUPPORTED_VERSIONS = (VERSION, SOURCE_PERIOD_VERSION, EXACT_SOURCE_PERIOD_VERSION)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Period(Contract):
    """Calendar periods, or exact source dates checked against the selected protocol.

    Source basis preserves the supplied dates and period kind; it does not infer
    a fiscal calendar, week count or a reporting period from duration alone.
    """
    kind: Literal["quarter", "ytd", "year", "instant"]
    start: date | None
    end: date
    basis: Literal["calendar", "source"] = Field(default="calendar", exclude_if=lambda value: value == "calendar")

    @model_validator(mode="after")
    def valid_range(self):
        if self.kind == "instant":
            if self.start is not None:
                raise ValueError("instant period cannot have a start")
        elif self.start is None or self.start > self.end:
            raise ValueError("duration requires an ordered start/end")
        elif self.basis == "calendar" and (self.start.year != self.end.year or self.start.day != 1 or self.end.day != monthrange(self.end.year, self.end.month)[1]
              or (self.kind == "quarter" and (self.start.month not in (1, 4, 7, 10) or self.end.month - self.start.month != 2))
              or (self.kind == "ytd" and (self.start.month != 1 or self.end.month not in (3, 6, 9)))
              or (self.kind == "year" and (self.start.month != 1 or self.end.month != 12))):
            raise ValueError("pilot supports calendar fiscal periods only")
        return self


class SourceMonthPeriod(Period):
    """v0.4 source periods retain complete month boundaries and supported duration."""

    @model_validator(mode="after")
    def complete_source_months(self):
        if self.basis == "source" and self.kind != "instant":
            months = (self.end.year - self.start.year) * 12 + self.end.month - self.start.month + 1
            expected = {"year": (12,), "quarter": (3,), "ytd": (6, 9)}[self.kind]
            if self.start.day != 1 or self.end.day != monthrange(self.end.year, self.end.month)[1] or months not in expected:
                raise ValueError("source periods require explicit complete month boundaries and supported duration")
        return self


class CalendarPeriod(Contract):
    """Calendar fiscal periods only; other fiscal calendars require a new adapter."""
    kind: Literal["quarter", "ytd", "year", "instant"]
    start: date | None
    end: date

    @model_validator(mode="after")
    def calendar_only(self):
        Period.model_validate(self.model_dump())
        return self


def validate_period_version(period, version):
    """The dataset selects the protocol; source basis cannot bypass legacy limits."""
    if version not in SUPPORTED_VERSIONS:
        raise ValueError("unsupported query contract version: " + version)
    if period is not None:
        value = period.model_dump(mode="json") if isinstance(period, Period) else period
        model = {VERSION: CalendarPeriod, SOURCE_PERIOD_VERSION: SourceMonthPeriod,
                 EXACT_SOURCE_PERIOD_VERSION: Period}[version]
        model.model_validate(value)


def export_query_schema(model, *, version):
    """Explicit storage protocol export, separate from current runtime models."""
    if version not in SUPPORTED_VERSIONS:
        raise ValueError("unsupported query contract version: " + version)
    schema = model.model_json_schema()
    period_model = {VERSION: CalendarPeriod, SOURCE_PERIOD_VERSION: SourceMonthPeriod,
                    EXACT_SOURCE_PERIOD_VERSION: Period}[version]
    period_schema = period_model.model_json_schema()
    period_schema["title"] = "Period"
    period_schema["$comment"] = (
        "Dates use ISO 8601. Cross-field ordering and calendar/month-boundary constraints "
        "are validated by validate_period_version using the enclosing dataset protocol."
    )
    period_schema["x-period-validation"] = {
        "protocol": version,
        "calendar": "calendar_boundaries",
        "source": {VERSION: "unsupported", SOURCE_PERIOD_VERSION: "complete_month_boundaries",
                   EXACT_SOURCE_PERIOD_VERSION: "ordered_exact_dates"}[version],
        "duration_start": "required_nonnull_and_not_after_end",
        "instant_start": "required_null",
    }
    if model is Period:
        schema = period_schema
    elif "Period" in schema.get("$defs", {}):
        schema["$defs"]["Period"] = period_schema
    schema["x-query-contract-version"] = version
    # Runtime models can read supported versions; each exported protocol has its own
    # record/result marker, including nested ResearchRecord definitions.
    def markers(node):
        if isinstance(node, dict):
            for key in ("schema_version", "result_schema_version"):
                field = node.get("properties", {}).get(key)
                if field is not None and field.get("default") == VERSION:
                    field["default"] = version
                    field["const"] = version
            for value in node.values():
                markers(value)
        elif isinstance(node, list):
            for value in node:
                markers(value)
    markers(schema)
    return schema


class ResearchRecord(Contract):
    schema_version: str = VERSION
    record_id: str
    record_type: Literal["metric", "guidance", "statement"]
    entity_id: str
    metric_id: str
    period: Period | None
    period_resolution: Literal["resolved", "unresolved", "not_applicable"] = "resolved"
    value_kind: Literal["actual", "management_guidance", "attributed_statement"]
    value_decimal: str | None
    upper_decimal: str | None = None
    value_relation: Literal["eq", "approx", "gt", "gte", "range", "qualitative", "unresolved"]
    unit: str | None
    denominator: str | None = None
    modality: str | None = None
    accounting_basis: str
    dimensions: dict[str, str] = Field(default_factory=dict)
    available_at: date
    source_snapshot_id: str
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    qualifier_evidence_ids: tuple[str, ...] = ()
    question_evidence_ids: tuple[str, ...] = ()
    summary: str
    speaker: str | None = None
    status: Literal["candidate"] = "candidate"
    origin: dict
    normalization_notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_value(self):
        validate_period_version(self.period, self.schema_version)
        if (self.period is not None) != (self.period_resolution == "resolved"):
            raise ValueError("period and resolution status disagree")
        for value in (self.value_decimal, self.upper_decimal):
            if value is not None:
                try:
                    d = Decimal(value)
                except InvalidOperation as error:
                    raise ValueError("value must be a decimal string") from error
                if not d.is_finite() or d.copy_abs() >= Decimal("1e26") or d != d.quantize(Decimal("0.000000000001"), context=Context(prec=50)):
                    raise ValueError("value is not representable as DECIMAL(38,12)")
        if self.value_relation == "qualitative" and (self.value_decimal is not None or self.upper_decimal is not None):
            raise ValueError("qualitative records cannot contain point estimates")
        if self.value_relation in ("eq", "approx", "gt", "gte", "range") and self.value_decimal is None:
            raise ValueError("numeric relation requires value")
        if self.value_relation == "range":
            if self.upper_decimal is None or Decimal(self.value_decimal) > Decimal(self.upper_decimal):
                raise ValueError("range requires ordered bounds")
        elif self.upper_decimal is not None:
            raise ValueError("upper bound requires range")
        if self.unit == "percent" and not self.denominator:
            raise ValueError("percentage requires an explicit denominator")
        return self


class RecordRequest(Contract):
    entity_id: str = Field(min_length=1, max_length=100, pattern=r"\S")
    metric_id: str = Field(min_length=1, max_length=100, pattern=r"\S")
    period: Period | None
    value_kind: Literal["actual", "management_guidance", "attributed_statement"] = "actual"


class DocumentRequest(Contract):
    company_id: str = Field(min_length=1, max_length=100, pattern=r"\S",
                            description="Explicit company identifier from source discovery; no default company.")
    form: Literal["10-K", "10-Q", "EARNINGS_CALL"]
    period_end: date
    phrase: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=2, ge=1, le=4)

    @model_validator(mode="after")
    def nonblank_phrase(self):
        if not self.phrase.strip():
            raise ValueError("document phrase cannot be blank")
        return self


class CalculationRequest(Contract):
    formula_id: Literal["operating_margin", "revenue_yoy", "operating_income_yoy", "operating_margin_delta_pp"]
    entity_id: str = Field(min_length=1, max_length=100, pattern=r"\S")
    periods: tuple[Period, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def arity(self):
        if len(self.periods) != (1 if self.formula_id == "operating_margin" else 2):
            raise ValueError("invalid formula arity; paired periods are prior, current")
        return self


class DataQuery(Contract):
    query_id: str = Field(min_length=1, max_length=120)
    question: str = Field(default="", max_length=4000)
    snapshot_id: str
    source_policy_id: Literal["local-frozen-v1"] = "local-frozen-v1"
    knowledge_cutoff: date
    include_candidates: bool = False
    records: tuple[RecordRequest, ...] = Field(default=(), max_length=16)
    documents: tuple[DocumentRequest, ...] = Field(default=(), max_length=4)
    calculations: tuple[CalculationRequest, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def executable(self):
        if not (self.records or self.documents or self.calculations):
            raise ValueError("provide a resolved query plan; question alone is not an executable plan")
        return self


class QueryResult(Contract):
    result_schema_version: str = VERSION
    query_id: str
    snapshot_id: str
    source_policy_id: str
    knowledge_cutoff: date
    candidate_data: bool
    status: Literal["complete", "partial", "ambiguous", "unanswerable", "failed"]
    completion_scope: str
    records: tuple[ResearchRecord, ...] = ()
    selections: tuple[dict, ...] = ()
    computed_facts: tuple[dict, ...] = ()
    documents: tuple[dict, ...] = ()
    evidence: dict[str, dict] = Field(default_factory=dict)
    gaps: tuple[dict, ...] = ()
    trace: tuple[dict, ...] = ()

    @model_validator(mode="after")
    def consistent_versions(self):
        if self.result_schema_version not in SUPPORTED_VERSIONS:
            raise ValueError("unsupported result schema version")
        if any(record.schema_version != self.result_schema_version for record in self.records):
            raise ValueError("record and result schema versions disagree")
        return self
