"""Host-only observation contract; never part of a model's input packet."""
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 'agent-observation-v1'
EVENT_TYPES = frozenset({'run.started', 'run.finished', 'step.started', 'step.action_started',
    'step.finished', 'model_call.started', 'model_call.finished', 'artifact.published'})


class ObservationError(RuntimeError):
    """A latched host recording fault, not a recoverable model decision error."""


@dataclass(frozen=True)
class ObservationContext:
    recorder: Any
    run_id: str
    role: str
    output: Path
    parent_run_id: str | None = None
    parent_step_id: str | None = None
    step_id: str | None = None
    decision_index: int | None = None
    attempt: int | None = None

    def guard(self):
        self.recorder.guard()

    def emit(self, event_type, **data):
        return self.recorder.emit(self, event_type, data)

    def for_step(self, ordinal, *, namespace='turn'):
        return replace(self, step_id=f'{self.run_id}-{namespace}-{ordinal:03d}', decision_index=ordinal)

    def for_attempt(self, attempt):
        return replace(self, attempt=attempt)

    def publish(self, path, *, kind=None, artifact_id=None, **metadata):
        return self.recorder.publish(self, Path(path), kind=kind, artifact_id=artifact_id, **metadata)
