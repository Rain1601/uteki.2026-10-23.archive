"""One action contract shared by the prompt, JSON schema and local validation."""
from dataclasses import dataclass


DECISION_PROTOCOL_VERSION = 'data-agent-decision-v1'


@dataclass(frozen=True)
class ActionRule:
    payload: str | None
    references: bool = False
    reason: bool = False


ACTION_RULES = {
    'plan': ActionRule('requirements', reason=True),
    'query': ActionRule('plan', references=True),
    'outline_source': ActionRule('outline', references=True),
    'read_source': ActionRule('read', references=True),
    'search_source': ActionRule('search', references=True),
    'read_context': ActionRule('context', references=True),
    'reread': ActionRule('evidence_ids', references=True),
    'extract': ActionRule('extracts', references=True),
    'answer': ActionRule('answer', references=True),
    'acquire': ActionRule('arguments', references=True),
    'materialize': ActionRule('arguments', references=True),
    'load_skill': ActionRule('skill'),
    'gap': ActionRule(None, references=True, reason=True),
    'finish': ActionRule(None),
    'discover_catalog': ActionRule('catalog'),
    'probe_schema': ActionRule('schema_probe'),
    'read_artifact': ActionRule('artifact_read'),
    'list_artifacts': ActionRule(None),
    'delegate': ActionRule('delegation', references=True),
    'financial_extract': ActionRule('financial_extraction', references=True),
}
ARRAY_PAYLOADS = frozenset({'requirements', 'evidence_ids', 'extracts'})


def action_schema_rules(schema):
    """Expose conditional requirements that Pydantic after-validators cannot infer."""
    rules = []
    # One conditional per payload avoids repeating every other empty payload in
    # every action branch. This matters because the schema is sent each turn.
    for field in sorted({r.payload for r in ACTION_RULES.values()} - {None}):
        actions = [action for action, rule in ACTION_RULES.items() if rule.payload == field]
        present = {'minItems': 1} if field in ARRAY_PAYLOADS else {'not': {'type': 'null'}}
        absent = {'maxItems': 0} if field in ARRAY_PAYLOADS else {'type': 'null'}
        rules.append({'if': {'properties': {'action': {'enum': actions}}, 'required': ['action']},
                      'then': {'required': [field], 'properties': {field: present}},
                      'else': {'properties': {field: absent}}})
    for attribute, field, constraint in (
        ('references', 'requirement_ids', {'minItems': 1}),
        ('reason', 'reason', {'type': 'string', 'minLength': 1, 'pattern': r"\S"}),
    ):
        actions = [action for action, rule in ACTION_RULES.items() if getattr(rule, attribute)]
        rules.append({'if': {'properties': {'action': {'enum': actions}}, 'required': ['action']},
                      'then': {'required': [field], 'properties': {field: constraint}}})
    schema['allOf'] = rules


def action_protocol_prompt():
    rows = ['Decision protocol ' + DECISION_PROTOCOL_VERSION + ':',
        'Return exactly one JSON object. No Markdown fences, XML, prose, duplicate keys, NaN or Infinity.',
        'Use exactly one action payload below. Omit other payload fields (or leave them null/empty).',
        'requirement_ids must be unique nonblank IDs from the current packet requirements.',
        'Action | payload field | additional required fields']
    for action, rule in ACTION_RULES.items():
        required = (['requirement_ids (nonempty)'] if rule.references else []) + (
            ['reason (nonblank)'] if rule.reason else [])
        rows.append(f'{action} | {rule.payload or "none"} | {", ".join(required) or "none"}')
    rows.extend([
        'Payload arrays must be nonempty. read_artifact may omit requirement_ids; include them when attaching evidence.',
        'read_artifact.artifact_read.limit is 1..1000 (characters for text, items for arrays). '
        'Copy pending_body_reads.read_request exactly; do not increase the limit past 1000.',
        'Before returning, check the action row, required fields, active scope and pending body reads.',
        'A rejected decision executes no action. Correct the named rule on the next bounded turn; '
        'do not repeat the same invalid decision or assume it succeeded.',
        'Protocol example only: {"action":"load_skill","skill":"query"}. '
        'A finish decision is {"action":"finish"}; the host still checks completion.',
    ])
    return '\n'.join(rows) + '\n'
