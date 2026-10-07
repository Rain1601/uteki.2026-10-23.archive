"""One lossless JSON code-fence recovery, never truncated/partial extraction."""
import re
from uteki.agents.runtime.strict_json import parse_json_object

def unwrap_json_fence(text):
    match=re.fullmatch(r'\s*```json\r?\n([\s\S]*?)\r?\n```\s*',text)
    if not match or '```' in match.group(1):
        raise ValueError('one_complete_json_fence_only')
    return parse_json_object(match.group(1))
