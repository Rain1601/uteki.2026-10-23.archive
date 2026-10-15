"""A deliberately small, shared read-only contract for SDK integration tests."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ReadRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    record_id: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class Delivery(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    result_ref: str
    value: str
    unit: str


@dataclass
class ProbeOutcome:
    kernel: str
    status: Literal['completed', 'invalid_delivery', 'error', 'cancelled', 'missing_terminal']
    delivery: dict | None = None
    reason: str | None = None
    native_events: list[dict] = field(default_factory=list)
    native_usage: list[dict | None] = field(default_factory=list)
    gateway_cost_usd: str | None = None
    # SDK estimates are neither OpenRouter bills nor proof that missing usage is zero.
    native_cost_estimate_usd: float | None = None


class FixtureStore:
    """Only caller-supplied synthetic bytes; no filesystem/network tool capability."""

    def __init__(self, raw: bytes):
        document = json.loads(raw)
        if document.get('kind') != 'synthetic-sdk-fixture-v1':
            raise ValueError('explicit synthetic fixture required')
        records = document.get('records')
        if not isinstance(records, dict) or not records:
            raise ValueError('fixture records required')
        for key, record in records.items():
            if not isinstance(key, str) or not key or not isinstance(record, dict):
                raise ValueError('invalid fixture record')
            if set(record) != {'value', 'unit'} or not all(isinstance(v, str) and v for v in record.values()):
                raise ValueError('fixture value and unit must be explicit strings')
        self.snapshot_sha256 = hashlib.sha256(raw).hexdigest()
        self._records = deepcopy(records)
        self.exposed: dict[str, dict] = {}
        self.calls: list[dict] = []

    def read(self, arguments: dict) -> dict:
        try:
            request = ReadRequest.model_validate(arguments)
        except ValidationError:
            return {'status': 'error', 'code': 'invalid_arguments'}
        self.calls.append(request.model_dump())
        if request.snapshot_sha256 != self.snapshot_sha256:
            return {'status': 'error', 'code': 'snapshot_mismatch'}
        if request.record_id not in self._records:
            return {'status': 'error', 'code': 'record_not_found'}
        record = self._records[request.record_id]
        reference = f'fixture:{self.snapshot_sha256}:{request.record_id}'
        result = {'status': 'ok', 'result_ref': reference, **record,
                  'snapshot_sha256': self.snapshot_sha256}
        self.exposed[reference] = deepcopy(result)
        return deepcopy(result)

    def validate_delivery(self, output: object) -> dict:
        delivery = Delivery.model_validate(output)
        observed = self.exposed.get(delivery.result_ref)
        if observed is None:
            raise ValueError('unread_result_ref')
        if (delivery.value, delivery.unit) != (observed['value'], observed['unit']):
            raise ValueError('value_or_unit_mismatch')
        return delivery.model_dump()


def finish(kernel: str, store: FixtureStore, output: object, **metadata) -> ProbeOutcome:
    try:
        delivery = store.validate_delivery(output)
    except (ValueError, TypeError):
        return ProbeOutcome(kernel, 'invalid_delivery', reason='unread_or_invalid_result', **metadata)
    return ProbeOutcome(kernel, 'completed', delivery=delivery, **metadata)
