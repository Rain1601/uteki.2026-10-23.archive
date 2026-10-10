#!/usr/bin/env python3
"""Compose caller-pinned complete filings for E5; no model or semantic selection.

Input schema: e5-explicit-full-datasets-v1, knowledge_cutoff, source_policy_id,
include_candidates, sources [{dataset, manifest_sha256, company_id,
source_snapshot_id, content_sha256, form, period_end, available_at}].
Paths are repository-relative and relocation-safe.
This is an experiment adapter for build_dataset, not multi-company acquisition.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import sys
from typing import Literal

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))

from pydantic import Field, model_validator

from uteki.agents.reading.document_reader import DocumentReader
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.domain.research_data.query_contract import Contract
from uteki.infrastructure.document_sources.filing_integrity import validate_sec_filing
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_dataset import build_dataset, save
from uteki.infrastructure.research_data.query_service import QueryDataPort


class Selection(Contract):
    dataset: str = Field(min_length=1)
    manifest_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    company_id: str = Field(pattern=r'^sec-[0-9]{10}$')
    source_snapshot_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')
    content_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    form: Literal['10-K', '10-K/A']
    period_end: date
    available_at: date


class PreparationInput(Contract):
    schema_version: Literal['e5-explicit-full-datasets-v1']
    knowledge_cutoff: date
    source_policy_id: Literal['local-frozen-v1']
    include_candidates: bool = Field(strict=True)
    sources: tuple[Selection, ...] = Field(min_length=2, max_length=64)

    @model_validator(mode='after')
    def multi_company(self):
        companies = {s.company_id for s in self.sources}
        if not 2 <= len(companies) <= 16:
            raise ValueError('select between two and sixteen distinct companies')
        ids = [s.source_snapshot_id for s in self.sources]
        if len(set(ids)) != len(ids) or len(ids) > 64:
            raise ValueError('selected sources must be globally unique and at most 64')
        return self


def local_path(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('repository-relative contained path required')
    path = root / relative
    if any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(root)):
        raise ValueError('symlink inputs are not supported')
    if not path.resolve().is_relative_to(root):
        raise ValueError('path leaves repository')
    return path


def prepare(input_path, repository, output):
    repository, output = Path(repository).resolve(), Path(output).absolute()
    if not output.is_relative_to(repository):
        raise ValueError('output must be in the repository for the existing builder')
    output = local_path(repository, output.relative_to(repository))
    if output.exists():
        raise FileExistsError('preparation output exists; preserve frozen outputs')
    config_bytes = Path(input_path).read_bytes()
    config = PreparationInput.model_validate_json(config_bytes)
    before, selected = {}, []

    def verified(path, expected):
        raw = path.read_bytes()
        if digest(raw) != expected:
            raise ValueError('pinned file hash mismatch: ' + str(path.relative_to(repository)))
        before[path] = expected
        return raw

    def pinned(path):
        return {'path': str(path.relative_to(repository)), 'sha256': digest(path.read_bytes())}

    # All checks precede publication. Company and report identity also come from
    # the original inline DEI declarations, never from a filename or a question.
    for selection in config.sources:
        dataset = local_path(repository, selection.dataset)
        if output == dataset or output.is_relative_to(dataset) or dataset.is_relative_to(output):
            raise ValueError('output overlaps a selected frozen dataset')
        manifest_path = local_path(dataset, 'manifest.json')
        manifest = json.loads(verified(manifest_path, selection.manifest_sha256))
        if manifest.get('source_policy_id') != config.source_policy_id:
            raise ValueError('dataset source policy differs from caller policy')
        for relative, expected in manifest['files'].items():
            path = local_path(repository, str((dataset / relative).relative_to(repository)))
            if not path.is_relative_to(dataset):
                raise ValueError('dataset file leaves selected dataset')
            verified(path, expected)
        for required in ('sources.json', 'records.json', 'metrics.json', 'research.duckdb'):
            if required not in manifest['files']:
                raise ValueError('dataset manifest omits ' + required)
        with QueryDataPort(dataset) as port:
            sources = {s['source_snapshot_id']: s for s in port.sources}
            if len(sources) != len(port.sources):
                raise ValueError('ambiguous source identity')
            records = json.loads((dataset / 'records.json').read_bytes())['rows']
            for sid in (selection.source_snapshot_id,):
                if sid not in sources or sources[sid]['company_id'] != selection.company_id:
                    raise ValueError('selected source absent or company mismatch')
                source = sources[sid]
                for key, expected in (('source_sha256', selection.content_sha256), ('form', selection.form),
                                      ('period_end', str(selection.period_end)),
                                      ('available_at', str(selection.available_at))):
                    if source.get(key) != expected:
                        raise ValueError('selected source metadata mismatch: ' + key)
                if date.fromisoformat(source['available_at']) > config.knowledge_cutoff:
                    raise ValueError('selected source unavailable at cutoff')
                if source['form'] not in {'10-K', '10-K/A'} or source['status'] != 'candidate':
                    raise ValueError('this experiment supports complete candidate SEC annual HTML filings')
                raw_path = local_path(dataset, source['raw_file'])
                if raw_path.suffix.lower() not in {'.html', '.htm'}:
                    raise ValueError('uncompressed original HTML is required')
                raw = verified(raw_path, source['source_sha256'])
                if manifest['files'].get(source['raw_file']) != source['source_sha256']:
                    raise ValueError('original bytes are not pinned by dataset manifest')
                identity = validate_sec_filing(raw, selection.company_id[4:], source['form'], source['period_end'])
                index_folder = local_path(dataset, source['index_folder'])
                reader = DocumentReader(index_folder)
                if (reader.manifest['source_sha256'] != source['source_sha256']
                        or reader.index['index_id'] != source['index_id']):
                    raise ValueError('source and full index identity differ')
                # Copy the reader's complete navigation inputs and their sibling
                # artifacts. No block IDs, sections, metrics, values or gold data
                # are caller-selectable here. Full parsed-package export is not
                # claimed; build_dataset's index_files protocol is flat.
                index_names = {'manifest.json', 'index.json', 'blocks.jsonl', *reader.manifest['artifacts']}
                index_files = []
                for name in sorted(index_names):
                    if Path(name).name != name:
                        raise ValueError('builder requires flat navigation artifacts')
                    path = local_path(dataset, str((index_folder / name).relative_to(dataset)))
                    if str(path.relative_to(dataset)) not in manifest['files']:
                        raise ValueError('navigation file is not pinned by dataset manifest')
                    index_files.append(pinned(path))
                entities = sorted({selection.company_id, *[r['entity_id'] for r in records
                                                           if r['source_snapshot_id'] == sid]})
                selected.append((source, raw_path, index_files, entities, len(reader.blocks), identity))

    output.mkdir(parents=True)
    (output / 'input.json').write_bytes(config_bytes)
    inventory, bindings, inputs = [], [], []
    for source, raw_path, index_files, entities, block_count, identity in selected:
        sid = source['source_snapshot_id']
        source_manifest = output / 'source-metadata' / (sid + '.json')
        save(source_manifest, {'source_snapshot_id': sid, 'company_id': source['company_id'],
            'document_id': source['document_id'], 'content_sha256': source['source_sha256'],
            'filed_at': source['available_at'], 'form': source['form'], 'period_end': source['period_end'],
            'identity_validation': identity})
        inventory.append({'source_snapshot_id': sid, 'document_id': source['document_id'],
            'eligible_for_new_comparison': True, 'declared_content_sha256': source['source_sha256'],
            'source_manifest': pinned(source_manifest), 'raw_file': pinned(raw_path),
            'published_or_filed_at': source['available_at'], 'period_end': source['period_end'],
            'source_url': source['source_url'], 'index_files': index_files})
        bindings.append({'source_snapshot_id': sid, 'company_id': source['company_id'],
            'entity_ids': entities, 'content_sha256': source['source_sha256']})
        inputs.append({**pinned(raw_path), 'source_snapshot_id': sid, 'adapter': 'us-gaap-inline-v1'})
    save(output / 'inventory.json', {'sources': inventory})
    save(output / 'build-spec.json', {'spec_version': 'query-build-v1',
        'source_inventory': pinned(output / 'inventory.json'), 'sources': bindings, 'inputs': inputs})
    manifest = build_dataset(repository, output / 'dataset', spec=output / 'build-spec.json')
    scope = ExecutionScope(snapshot_id=manifest['snapshot_id'],
        company_ids=tuple(sorted({s.company_id for s in config.sources})),
        source_snapshot_ids=tuple(s['source_snapshot_id'] for s, *_ in selected),
        source_policy_id=config.source_policy_id, knowledge_cutoff=config.knowledge_cutoff,
        include_candidates=config.include_candidates)
    preserved = []
    with QueryDataPort(output / 'dataset') as port:
        port.scoped(scope).discover_data()
        built_sources = {s['source_snapshot_id']: s for s in port.sources}
        for source, raw_path, index_files, entities, block_count, identity in selected:
            built = built_sources[source['source_snapshot_id']]
            if digest((output / 'dataset' / built['raw_file']).read_bytes()) != source['source_sha256']:
                raise ValueError('built source bytes changed')
            for original in index_files:
                target = output / 'dataset' / built['index_folder'] / Path(original['path']).name
                if digest(target.read_bytes()) != original['sha256']:
                    raise ValueError('complete navigation artifact changed')
            preserved.append({'source_snapshot_id': source['source_snapshot_id'],
                'company_id': source['company_id'], 'source_sha256': source['source_sha256'],
                'full_index_block_count': block_count, 'original_and_navigation_bytes_preserved': True})
    for path, expected in before.items():
        verified(path, expected)
    save(output / 'scope.json', scope.model_dump(mode='json'))
    normalization_gaps = manifest.get('normalization_gaps', [])
    result = {'schema_version': 'e5-full-source-preparation-result-v1',
        'status': 'prepared_with_gaps' if normalization_gaps else 'prepared',
        'input_sha256': digest(config_bytes), 'dataset': str((output / 'dataset').relative_to(repository)),
        'dataset_manifest_sha256': digest((output / 'dataset' / 'manifest.json').read_bytes()),
        'scope': scope.model_dump(mode='json'), 'sources': preserved,
        'model_calls': 0, 'semantic_selection': False, 'input_files_verified_unchanged': len(before),
        'normalization_gap_count': len(normalization_gaps),
        'normalization_gap_reasons': dict(Counter(g.get('reason', 'unspecified') for g in normalization_gaps)),
        'normalization_gaps_ref': 'dataset/manifest.json#/normalization_gaps',
        'limits': ['Caller-pinned complete reports; no cross-company network discovery.',
                   'Navigation index and original HTML preserved; full parsed-package export is not claimed.',
                   'Candidate generic inline records only; no semantic or coverage acceptance.']}
    save(output / 'result.json', result)
    save(output / 'manifest.json', {'schema_version': 'e5-full-source-preparation-artifacts-v1',
        'files': {str(p.relative_to(output)): digest(p.read_bytes())
                  for p in sorted(output.rglob('*')) if p.is_file()}})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--repository', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.input, args.repository, args.output), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
