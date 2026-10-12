"""One action contract shared by the prompt, JSON schema and local validation."""
from dataclasses import dataclass


DECISION_PROTOCOL_VERSION = 'data-agent-decision-v6-selection-ownership'

SOURCE_SELECTION_RULE = (
    'select_evidence applies one identical delivery.blocks list to EVERY requirement_id; '
    'it does not distribute a union of blocks among requirements. Prefer one requirement per action. '
    'Batch only requirements with the same source_id and pinned scope that need the identical blocks. '
    'For different sources, report versions or intended block sets, issue separate actions. '
    'Each selected context/block must be fully read by this role and match every selected requirement. '
    'The host rejects the whole invalid selection without changing prior selections; '
    'it never assigns blocks to requirements for you.')

# Native transports replace this host-object example with wire-envelope examples.
# Keep a named literal so the adapter removes only our own text, not user input.
HOST_DECISION_EXAMPLE = ('Protocol example only: {"action":"load_skill","skill":"query"}. '
                         'A finish decision is {"action":"finish"}; the host still checks completion.')


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
    'select_evidence': ActionRule('delivery', references=True, reason=True),
    'select_records': ActionRule('record_selection', references=True, reason=True),
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
        SOURCE_SELECTION_RULE,
        'select_records likewise applies the entire record_ids list to every requirement_id; '
        'each must have returned every selected record in its own pinned query. Use separate actions '
        'when the intended record sets differ. Source ownership does not establish semantic relevance.',
        'Requirement field rules apply before the first plan, not only after a rejection:',
        'kind=query: include query (a QueryPlan); omit node_id. Optional source_id pins this requirement to one '
        'source from the active catalog; omit source_id to query the entire active scope. '
        'For distinct report versions, create separate requirements with their own source_id and query each separately. '
        'Every requirement_id in one query action must have the same source selection. '
        'Never resolve ambiguity by choosing the first/latest record or discarding a requested report.',
        'kind=source_evidence or source_answer: include source_id from the scoped catalog; omit node_id and query.',
        'kind=read_node: include source_id and node_id returned by the scoped outline; omit query.',
        'kind=information: omit source_id, node_id and query; this kind does not prove body reading.',
        'kind=financial_extract: include financial_task_id and batch_index from registered tasks; '
        'omit source_id, node_id and query. Other kinds must omit financial_task_id and batch_index.',
        'Payload arrays must be nonempty. read_artifact may omit requirement_ids; include them when attaching evidence.',
        'read_artifact.artifact_read.limit is 1..1000 (characters for text, items for arrays). '
        'Copy pending_body_reads.read_request exactly; do not increase the limit past 1000.',
        'Before returning, check the action row, required fields, active scope and pending body reads.',
        'A rejected decision executes no action. Correct the named rule on the next bounded turn; '
        'do not repeat the same invalid decision or assume it succeeded.',
        HOST_DECISION_EXAMPLE,
    ])
    return '\n'.join(rows) + '\n'
