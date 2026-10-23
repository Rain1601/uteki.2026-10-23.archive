"""Restore opaque OpenRouter reasoning blocks from bound, durable wire receipts.

The official Chat adapter currently drops ``reasoning_details``. Keep its
Runner/tool loop and restore only this provider field before request admission
and hashing. This is a project adapter, not an Agents SDK replay capability.
"""
from copy import deepcopy
import json

from ...contracts.common import CatalogError, canonical
from .openrouter_evidence import response_bytes


# 使用调用 ID、类型、工具名与原始参数组成关联键，避免仅靠内容文本匹配历史消息。
def _calls(message):
    calls = message.get('tool_calls') or []
    return [(c['id'], c['type'], c['function']['name'], c['function']['arguments']) for c in calls]


# 项目适配：从本次已消费请求的原始收据补回供应商字段，保持官方 Runner 的原生循环。
def restore_reasoning(raw, state):
    """Use the consumed request prefix, never a process cache or another run.

    Missing/conflicting history fails closed. Requests without opaque reasoning
    keep their original bytes, including historical replay hashes.
    """
    journal = state.journal
    if journal.profile['route']['provider'] != 'openrouter':
        return raw
    try:
        history = journal.session().data['native_execution'].get('openai_requests', [])
        if not 0 <= state.cursor <= len(history):
            raise ValueError('invalid consumed request prefix')
        sources = []
        # 只使用当前恢复游标之前已确认的请求，禁止跨运行、跨模型或借用未来响应。
        for item in history[:state.cursor]:
            record = journal.budget.inspect_request(item['request_key'])
            if (not state.record_matches(record, state.read(item['request_ref']))
                    or record['stage'] != 'responded' or record['cost_state'] not in {'settled', 'bounded'}
                    or record['response_event']['response'].get('complete') is not True):
                raise ValueError('unbound or incomplete reasoning receipt')
            captured = record['response_event']['response']['http']
            if (captured['protocol'] != 'chat_completions' or captured['status'] != 200
                    or not captured['transport_complete']):
                raise ValueError('reasoning requires a complete Chat receipt')
            response = json.loads(response_bytes(captured))
            choices = response['choices']
            if (response['model'] != journal.profile['model_id'] or len(choices) != 1
                    or choices[0]['index'] != 0 or choices[0]['message']['role'] != 'assistant'):
                raise ValueError('reasoning response model or choice differs')
            message = choices[0]['message']
            details = message.get('reasoning_details')
            if details is not None and (not isinstance(details, list)
                    or any(not isinstance(block, dict) for block in details)):
                raise ValueError('invalid reasoning_details array')
            # 不解释不透明思考块的语义；只有能精确绑定到工具调用的原始字段才允许恢复。
            if details:
                if not _calls(message):
                    raise ValueError('reasoning receipt is not bound to a tool call')
                sources.append(message)
        # 没有需恢复字段时原样返回字节，保持旧请求摘要及重放身份不变。
        if not sources:
            return raw
        body = json.loads(raw)
        if body['model'] != journal.profile['model_id']:
            raise ValueError('reasoning cannot cross models')
        messages = [m for m in body['messages'] if m['role'] == 'assistant' and m.get('tool_calls')]
        positions = []
        # 每段历史必须唯一匹配、保持顺序且助手正文一致，已有字段冲突时立即失败。
        for source in sources:
            matching = [(i, m) for i, m in enumerate(messages) if _calls(m) == _calls(source)]
            if len(matching) != 1:
                raise ValueError('reasoning tool call is absent or ambiguous')
            position, message = matching[0]
            if position in positions or (positions and position <= positions[-1]):
                raise ValueError('reasoning tool call order differs')
            positions.append(position)
            if (message.get('content') or None) != (source.get('content') or None):
                raise ValueError('reasoning assistant content differs')
            if ('reasoning_details' in message
                    and message['reasoning_details'] != source['reasoning_details']):
                raise ValueError('reasoning_details conflicts with the original receipt')
            message['reasoning_details'] = deepcopy(source['reasoning_details'])
        return canonical(body)
    except CatalogError:
        raise
    except (KeyError, TypeError, ValueError, IndexError) as error:
        raise CatalogError('RECOVERY_REQUIRED', 'cannot restore bound OpenRouter reasoning: '+str(error)) from error
