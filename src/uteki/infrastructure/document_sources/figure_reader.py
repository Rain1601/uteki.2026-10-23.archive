"""Read a source-bound figure supplement without weakening dataset provenance.

This consumer exposes original pixels, locally validated transcription and the
original filing's exact image locations. Protocol validity does not establish
visual accuracy; the independent acceptance status is returned separately.
"""
from __future__ import annotations

from copy import deepcopy
import csv
from io import StringIO
import math
import hashlib
import json
from pathlib import Path

from .figure_acquisition import _contained, discover_figures, inspect_image


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _validate_grounding(row, transcription, raw, info, verified, *, require_image_hash):
    from PIL import Image
    from uteki.agents.figure_materials import Figure
    from .figure_grounding import ANGLES, norm, original_box, replay_text_grounding

    grounding_path = row.get('grounding')
    grounding = json.loads(verified(grounding_path))
    if (grounding.get('adapter') != 'tesseract-multiangle-v1' or grounding.get('language') != 'eng'
            or grounding.get('status') != 'grounded' or grounding.get('gaps') != []
            or grounding.get('coordinate_space') != 'normalized_original_0_1000'
            or ((require_image_hash or 'image_sha256' in grounding) and grounding.get('image_sha256') != _sha(raw))
            or grounding.get('image_size') != [info['width'], info['height']]
            or grounding.get('angles') != list(ANGLES)):
        raise ValueError('Invalid figure coordinate grounding contract')
    matches, runs = grounding.get('matches'), grounding.get('runs')
    if not isinstance(matches, dict) or set(matches) != {text['id'] for text in transcription['texts']}:
        raise ValueError('Figure grounding must cover every source text identity')
    if not isinstance(runs, list) or len(runs) != len(ANGLES):
        raise ValueError('Figure grounding requires every bounded OCR run')
    ocr_runs = {}
    tsvs = {}
    for number, (run, angle) in enumerate(zip(runs, ANGLES)):
        expected_size = list(Image.new('1', (info['width'], info['height'])).rotate(angle, expand=True).size)
        if run.get('angle') != angle or run.get('tsv') != f'ocr-{number}.tsv' or run.get('size') != expected_size:
            raise ValueError('Figure OCR transform metadata mismatch')
        relative = (Path(grounding_path).parent / run['tsv']).as_posix()
        tsv = verified(relative).decode('utf-8')
        tsvs[run['tsv']] = tsv
        lines = {}
        for word in csv.DictReader(StringIO(tsv), delimiter='\t'):
            if word['level'] == '5' and word.get('text', '').strip():
                key = tuple(word[key] for key in ('page_num', 'block_num', 'par_num', 'line_num'))
                lines.setdefault(key, []).append(word)
        ocr_runs[run['tsv']] = (run, lines)
    for text in transcription['texts']:
        match = matches[text['id']]
        if (not isinstance(match, dict) or match.get('text') != norm(text['text'])
                or match.get('box') != text['box'] or match.get('ocr_file') not in ocr_runs
                or type(match.get('confidence')) not in (int, float)
                or not math.isfinite(match['confidence']) or not 80 <= match['confidence'] <= 100):
            raise ValueError('Figure text/box differs from grounded OCR match')
        run, lines = ocr_runs[match['ocr_file']]
        if match.get('angle') != run['angle']:
            raise ValueError('Figure matched text transform mismatch')
        found = False
        for words in lines.values():
            for start in range(len(words)):
                for end in range(start + 1, min(len(words), start + 20) + 1):
                    part = words[start:end]
                    if norm(' '.join(word['text'] for word in part)) != match['text']:
                        continue
                    confidences = [float(word['conf']) for word in part]
                    if any(not math.isfinite(value) or not 80 <= value <= 100 for value in confidences):
                        continue
                    confidence = min(confidences)
                    pixel_box = (min(int(word['left']) for word in part), min(int(word['top']) for word in part),
                        max(int(word['left']) + int(word['width']) for word in part),
                        max(int(word['top']) + int(word['height']) for word in part))
                    candidate = original_box(pixel_box, run['angle'], run['size'], (info['width'], info['height']))
                    if confidence == match['confidence'] and candidate == match['box']:
                        found = True
        if not found:
            raise ValueError('Figure grounding match is absent from the pinned OCR words')
    if require_image_hash:
        # v3's strong coordinate status requires the producer's whole-inventory
        # decision, not just existence of a selected hit. Legacy v2 retains its
        # explicitly weaker historical validation and status.
        replayed, gaps = replay_text_grounding(transcription['texts'], runs, tsvs,
            (info['width'], info['height']))
        if gaps:
            codes = sorted({gap['code'] for gap in gaps})
            raise ValueError('Figure OCR replay has unresolved coordinates: ' + ', '.join(codes))
        if replayed != matches:
            raise ValueError('Figure grounding differs from the complete pinned OCR replay')
    model_path = (Path(row['transcription']).parent / 'model-transcription.json').as_posix()
    model = Figure.model_validate_json(verified(model_path)).model_dump()
    if {text['id'] for text in model['texts']} != set(matches):
        raise ValueError('Figure model text identities changed during grounding')
    for text in model['texts']:
        text['box'] = matches[text['id']]['box']
    if model != transcription:
        raise ValueError('Figure grounding changed semantic model output')


class FigureMaterialReader:
    def __init__(self, bundle, dataset):
        self.bundle = Path(bundle).resolve()
        self.dataset = Path(dataset).resolve()
        self._manifest_sha256 = _sha((self.bundle / 'manifest.json').read_bytes())
        self._load()

    def _load(self):
        """Validate each read, including changes after the reader was constructed."""
        from uteki.agents.figure_materials import Figure, VERSION

        manifest_raw = (self.bundle / 'manifest.json').read_bytes()
        if _sha(manifest_raw) != self._manifest_sha256:
            raise ValueError('Figure bundle manifest changed after opening')
        manifest = json.loads(manifest_raw)
        if manifest.get('version') not in {'figure-materials-v1', 'figure-materials-v2', 'figure-materials-v3'} or manifest.get('status') not in {'prepared', 'with_gaps'}:
            raise ValueError('Unsupported or incomplete figure bundle')
        discovered = discover_figures(self.dataset)
        if discovered['gaps'] or discovered['dataset_manifest_sha256'] != manifest.get('dataset_manifest_sha256'):
            raise ValueError('Figure dataset binding mismatch or unresolved index gaps')
        files = manifest.get('files')
        if not isinstance(files, dict) or not files:
            raise ValueError('Figure bundle requires pinned artifacts')
        def verified(relative):
            raw = _contained(self.bundle, relative).read_bytes()
            if _sha(raw) != files.get(relative):
                raise ValueError('Figure artifact hash mismatch: ' + relative)
            return raw
        for relative in files:
            verified(relative)
        config = json.loads(verified('config.json'))
        if config.get('dataset_manifest_sha256') != discovered['dataset_manifest_sha256']:
            raise ValueError('Figure configuration dataset binding mismatch')
        expected = {figure['figure_id']: figure for figure in discovered['figures']}
        if manifest.get('expected_figures') != len(expected):
            raise ValueError('Figure inventory count mismatch')
        rows = manifest.get('figures')
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError('Invalid figure records')
        actual = {row['figure_id']: row for row in rows}
        if len(actual) != len(rows) or set(actual) - set(expected):
            raise ValueError('Duplicate or out-of-scope figure identity')
        gaps = manifest.get('gaps')
        if not isinstance(gaps, list):
            raise ValueError('Invalid figure gap inventory')
        if manifest['status'] == 'prepared' and (gaps or set(actual) != set(expected)):
            raise ValueError('Prepared figure inventory is incomplete')
        if manifest['status'] == 'with_gaps':
            gap_ids = {gap.get('figure_id') for gap in gaps if isinstance(gap, dict)}
            if not gaps or set(expected) - set(actual) - gap_ids:
                raise ValueError('Missing figures have no explicit gaps')
        sources = {source['source_snapshot_id']: source for source in json.loads((self.dataset / 'sources.json').read_text())}
        result = {}
        for figure_id, row in actual.items():
            expected_status = 'ocr_grounded' if manifest['version'] != 'figure-materials-v1' else 'protocol_validated'
            if row.get('status') != expected_status:
                raise ValueError('Figure transcription status does not match bundle version')
            origin = json.loads(verified(row['source']))
            frozen = origin['figure']
            wanted = expected[figure_id]
            for field in ('figure_id', 'source_snapshot_id', 'company_id', 'document_source_url',
                          'source_sha256', 'source_url', 'locations'):
                if frozen.get(field) != wanted[field]:
                    raise ValueError('Figure source provenance mismatch: ' + field)
            original_raw = verified(row['original'])
            if (frozen.get('status') != 'frozen' or frozen.get('sha256') != _sha(original_raw)
                    or row.get('image_sha256') != _sha(original_raw) or frozen.get('bytes') != len(original_raw)):
                raise ValueError('Figure original image binding mismatch')
            info = inspect_image(original_raw, 4_000_000)
            if any(frozen.get(key) != value for key, value in info.items()):
                raise ValueError('Figure image decoding metadata mismatch')
            transcription = Figure.model_validate_json(verified(row['transcription'])).model_dump()
            if manifest['version'] != 'figure-materials-v1':
                _validate_grounding(row, transcription, original_raw, info, verified, require_image_hash=manifest['version'] == 'figure-materials-v3')
            source = sources[frozen['source_snapshot_id']]
            blocks = [json.loads(line) for line in _contained(self.dataset, source['index_folder'] + '/blocks.jsonl').read_text().splitlines()]
            selected = {location['block_id'] for location in wanted['locations']}
            source_blocks = [block for block in blocks if block['block_id'] in selected]
            context = {}
            for i, block in enumerate(blocks):
                if block['block_id'] in selected:
                    for neighbor in blocks[max(0, i - 6):i + 4]:
                        if neighbor.get('text', '').strip() and len(neighbor['text']) <= 6000:
                            context[neighbor['block_id']] = {key: neighbor[key] for key in ('block_id', 'dom_path', 'text', 'text_hash')}
            if origin.get('document_context') != list(context.values()):
                raise ValueError('Figure context differs from source blocks')
            result[figure_id] = {
                'figure_id': figure_id, 'company_id': wanted['company_id'],
                'source_snapshot_id': wanted['source_snapshot_id'],
                'source_url': wanted['source_url'], 'document_source_url': wanted['document_source_url'],
                'source_sha256': wanted['source_sha256'], 'image_sha256': frozen['sha256'],
                'original_image_path': str(_contained(self.bundle, row['original'])),
                'original_document_path': str(_contained(self.dataset, source['raw_file'])),
                'locations': wanted['locations'], 'source_blocks': source_blocks,
                'transcription': transcription, 'document_context': origin['document_context'],
                'status': row['status'], 'bundle_status': manifest['status'],
                'independent_acceptance': manifest.get('independent_acceptance', 'pending'),
                'coordinate_status': ('ocr_grounded' if manifest['version'] == 'figure-materials-v3'
                    else 'ocr_grounded_legacy_no_required_image_hash' if manifest['version'] == 'figure-materials-v2'
                    else 'unverified_model_coordinates'),
            }
        return result

    def list(self):
        """Small inventory; full transcripts are only loaded through read()."""
        return [{key: value[key] for key in ('figure_id', 'company_id', 'source_snapshot_id',
                'source_url', 'status', 'bundle_status', 'independent_acceptance', 'coordinate_status')}
                for value in self._load().values()]

    def read(self, figure_id):
        records = self._load()
        if not isinstance(figure_id, str) or figure_id not in records:
            raise ValueError('Unknown figure identity in selected bundle')
        return deepcopy(records[figure_id])
