"""Single frozen-image Claude transport; acquisition remains a host responsibility.

Input is exactly one user message with two content blocks, in order::

    [{"role": "user", "content": [
        {"type": "input_image", "image_url": "data:image/png;base64,..."},
        {"type": "input_text", "text": "Read the figure using the given schema."}
    ]}]

Only a fully decoded, single-frame JPEG/PNG/GIF/WebP up to 5 MB and 2000 x
2000 pixels is accepted. No URL fetching, conversion, resizing, tools or previous
conversation is performed. Callers freeze acquired bytes separately. The exact
base64 native request is fingerprinted and metered by the inherited transport.
The existing meter reserves actual serialized bytes plus its 16k-token overhead;
our single-image pixel ceiling (about 5334 image tokens before provider resizing)
fits inside that overhead. Both model and meter request byte limits still apply.

Use an explicit structured output schema. json_object is an instruction contract,
not a claim of provider-enforced JSON Schema; the SDK validates output locally.
"""
import base64
import binascii
from io import BytesIO
import re
import warnings

from PIL import Image, ImageFile

from .claude_messages import ClaudeMessagesModel, _canonical
from .run_budget import RequestEnvelopeTooLarge

MAX_IMAGE_BYTES = 5_000_000
MAX_IMAGE_DIMENSION = 2000
_DATA_URI = re.compile(r'data:(image/(?:jpeg|png|gif|webp));base64,([A-Za-z0-9+/]*={0,2})\Z')
_FORMATS = {'image/jpeg': 'JPEG', 'image/png': 'PNG', 'image/gif': 'GIF', 'image/webp': 'WEBP'}


def _frozen_image_packet(value):
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise ValueError('Claude vision requires strict image decoding')
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ValueError('Claude vision requires one user image packet')
    message = value[0]
    if (set(message) - {'role', 'content', 'type'} or message.get('role') != 'user'
            or message.get('type', 'message') != 'message'):
        raise ValueError('Claude vision requires one user image packet')
    content = message.get('content')
    if (not isinstance(content, list) or len(content) != 2
            or any(not isinstance(block, dict) for block in content)
            or set(content[0]) != {'type', 'image_url'} or content[0]['type'] != 'input_image'
            or set(content[1]) != {'type', 'text'} or content[1]['type'] != 'input_text'
            or not isinstance(content[1]['text'], str) or not content[1]['text'].strip()):
        raise ValueError('Claude vision requires one frozen image followed by nonempty text')
    uri = content[0]['image_url']
    # Bound before regex/base64 allocation. Prefix and padding account for <= 40 chars.
    if not isinstance(uri, str) or len(uri) > 4 * ((MAX_IMAGE_BYTES + 2) // 3) + 40:
        raise ValueError('Claude vision image exceeds its byte limit')
    match = _DATA_URI.fullmatch(uri)
    if match is None:
        raise ValueError('Claude vision accepts only supported base64 image data URIs')
    media_type, encoded = match.groups()
    valid = False
    try:
        raw = base64.b64decode(encoded, validate=True)
        valid = (0 < len(raw) <= MAX_IMAGE_BYTES
                 and base64.b64encode(raw).decode('ascii') == encoded)
        if valid:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as probe:
                    valid = (probe.format == _FORMATS[media_type]
                             and all(0 < size <= MAX_IMAGE_DIMENSION for size in probe.size)
                             and getattr(probe, 'n_frames', 1) == 1)
                    if valid:
                        probe.verify()
                if valid:
                    # verify() alone does not decode all formats' pixel data.
                    with Image.open(BytesIO(raw)) as decoded:
                        decoded.load()
    except (ValueError, OSError, SyntaxError, binascii.Error,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        valid = False
    if not valid:
        raise ValueError('Claude vision requires a complete supported single-frame image within limits')
    return {'type': 'image', 'source': {'type': 'base64', 'media_type': media_type, 'data': encoded}}, content[1]['text']


class ClaudeVisionModel(ClaudeMessagesModel):
    """Reuse bounded Messages transport with a required local JSON output schema."""

    def __init__(self, model, **kwargs):
        if kwargs.pop('schema_protocol', 'json_object') != 'json_object':
            raise ValueError('Claude vision requires json_object schema protocol')
        super().__init__(model, schema_protocol='json_object', **kwargs)

    def _request(self, system_instructions, input, model_settings, tools, output_schema, handoffs,
                 tracing=None, *, previous_response_id=None, conversation_id=None, prompt=None):
        image, text = _frozen_image_packet(input)
        if output_schema is None or output_schema.is_plain_text():
            raise ValueError('Claude vision requires a structured output schema')
        body, _, schema = super()._request(system_instructions, text, model_settings, tools,
            output_schema, handoffs, tracing, previous_response_id=previous_response_id,
            conversation_id=conversation_id, prompt=prompt)
        body['messages'] = [{'role': 'user', 'content': [image, {'type': 'text', 'text': text}]}]
        raw = _canonical(body)
        if len(raw) > self.max_request_bytes:
            raise RequestEnvelopeTooLarge('Native Claude image request exceeds configured byte capacity')
        return body, raw, schema
