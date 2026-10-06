"""Explicit, hash-pinned inputs for building a query dataset."""
from typing import Literal

from pydantic import Field, model_validator

from uteki.domain.research_data.query_contract import Contract


class InputFile(Contract):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SourceBinding(Contract):
    source_snapshot_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    company_id: str = Field(min_length=1, pattern=r"\S")
    entity_ids: tuple[str, ...] = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def valid_entities(self):
        if self.company_id not in self.entity_ids or any(not e.strip() for e in self.entity_ids):
            raise ValueError("source entities must explicitly include their company")
        return self


class NormalizationInput(InputFile):
    source_snapshot_id: str = Field(min_length=1)
    adapter: Literal["alphabet-financial-v1", "alphabet-call-reviewed-v1", "us-gaap-inline-v1"]


class DatasetBuildSpec(Contract):
    spec_version: Literal["query-build-v1"]
    source_inventory: InputFile
    sources: tuple[SourceBinding, ...] = Field(min_length=1)
    inputs: tuple[NormalizationInput, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_bindings(self):
        ids = [s.source_snapshot_id for s in self.sources]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate source binding")
        if any(i.source_snapshot_id not in ids for i in self.inputs):
            raise ValueError("normalization input references an unbound source")
        paths = [i.path for i in self.inputs]
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate normalization input")
        return self
