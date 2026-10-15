"""Persist public SDK checkpoints and replay only exact, durably answered requests."""
from copy import deepcopy
from importlib.metadata import version
import json
import uuid

from agents import ModelResponse, RunContextWrapper, RunState
from pydantic import TypeAdapter

from ..contracts.common import CatalogError, canonical
from ..contracts.content import ObjectRef


class OpenAIState:
    def __init__(self, journal, binding):
        self.journal, self.binding = journal, binding
        self.cursor = 0

    def read(self, reference):
        try:
            raw = self.journal.catalog.content.read_object(ObjectRef.model_validate(reference))
            value = json.loads(raw)
            if canonical(value) != raw:
                raise ValueError('noncanonical SDK state object')
            return value
        except (ValueError, OSError) as error:
            raise CatalogError('RECOVERY_REQUIRED','saved OpenAI state/request cannot be verified') from error

    async def load(self, agent):
        native = self.journal.state()
        if native.get('openai_checkpoint') is None:
            if self.journal.resuming:
                raise CatalogError('RECOVERY_REQUIRED','original OpenAI checkpoint is missing')
            state = RunState(RunContextWrapper(None),canonical(self.binding.context).decode(),agent,
                             self.journal.limits.native_max_turns)
            self.save(state)
            return state
        saved = self.read(native['openai_checkpoint'])
        requests = native.get('openai_requests',[])
        try:
            if (saved['format']!='uteki-openai-run-state-v1' or saved['sdk_version']!=version('openai-agents')
                    or saved['context_ref']!=self.journal.context_ref or saved['binding']!=native['binding']
                    or saved['native_session_id']!=native['native_session_id']
                    or requests[:len(saved['requests'])]!=saved['requests']):
                raise ValueError('checkpoint binding or request prefix differs')
            self.cursor = len(saved['requests'])
            keys = [r['request_key'] for r in requests]
            if len(keys)!=len(set(keys)):
                raise ValueError('duplicate physical request identity')
            records = [r for r in self.journal.budget.inspect_requests()
                       if r['request']['context_ref']==self.journal.context_ref]
            if not {r['request_key'] for r in records} <= set(keys):
                raise ValueError('a physical request is absent from the SDK request order')
            for item in requests[:self.cursor]:
                record = self.journal.budget.inspect_request(item['request_key'])
                if (record['stage']!='responded' or record['request']['profile']!=self.journal.profile
                        or record['request']['request']!=self.read(item['request_ref'])
                        or record['response_event']['response'].get('complete') is not True):
                    raise ValueError('checkpoint consumes a request without a complete bound response')
            visible = {canonical(r) for r in saved['visible_results']}
            if not visible <= {canonical(r) for r in native['observed_results']}:
                raise ValueError('checkpoint claims results not observed in this native run')
            state = await RunState.from_json(agent,saved['state'])
        except Exception as error:
            raise CatalogError('RECOVERY_REQUIRED','OpenAI checkpoint binding or public SDK restore failed') from error
        # Eligibility is not visibility: only the saved observed prefix is
        # visible now. Later replayed outputs must cross a model-input hook.
        self.binding.returned = [deepcopy(c['output']) for c in native['tool_calls'].values()
                                 if c['output'] is not None]
        self.binding.visible = visible
        return state

    def save(self, state):
        session = self.journal.session()
        native = session.data['native_execution']
        value = dict(format='uteki-openai-run-state-v1',sdk_version=version('openai-agents'),
            context_ref=self.journal.context_ref,native_session_id=native['native_session_id'],
            binding=native['binding'],requests=deepcopy(native.get('openai_requests',[])[:self.cursor]),
            visible_results=[json.loads(r) for r in sorted(self.binding.visible)],state=state.to_json())
        native['openai_checkpoint'] = self.journal.catalog.content.put_object(canonical(value)).model_dump(mode='json')
        session.save()
        self.journal.checkpoint('openai_state_committed')

    def request(self, request):
        session = self.journal.session()
        requests = session.data['native_execution'].setdefault('openai_requests',[])
        if self.cursor > len(requests):
            raise CatalogError('RECOVERY_REQUIRED','OpenAI request position is outside its durable history')
        if self.cursor == len(requests):
            item = dict(request_key='model:'+uuid.uuid4().hex,
                request_ref=self.journal.catalog.content.put_object(canonical(request)).model_dump(mode='json'))
            requests.append(item)
            session.save()
            self.journal.checkpoint('openai_request_intent')
        else:
            item = requests[self.cursor]
            if self.read(item['request_ref'])!=request:
                raise CatalogError('RECOVERY_REQUIRED','resumed SDK request differs from the original; no replay or resend')
        record = next((r for r in self.journal.budget.inspect_requests() if r['request_key']==item['request_key']),None)
        if record is not None:
            if record['request']!=dict(run_id=self.journal.context['run_id'],context_ref=self.journal.context_ref,
                                       profile=self.journal.profile,request=request):
                raise CatalogError('RECOVERY_REQUIRED','physical request and SDK intent bindings differ')
            if record['stage']=='responded':
                response = record['response_event']['response']
                if response.get('complete') is not True or record['cost_state']!='settled':
                    raise CatalogError('RECOVERY_REQUIRED','saved response or fee is incomplete')
                try:
                    value = TypeAdapter(ModelResponse).validate_python(response['response'])
                except (ValueError,KeyError) as error:
                    raise CatalogError('RECOVERY_REQUIRED','saved ModelResponse cannot be restored') from error
                self.cursor += 1
                self.journal.checkpoint('openai_response_replayed')
                return item['request_key'],value
            if record['stage']!='prepared':
                raise CatalogError('RECOVERY_REQUIRED','physical request outcome is unknown; never resend')
        return item['request_key'],None

    def responded(self):
        self.cursor += 1
