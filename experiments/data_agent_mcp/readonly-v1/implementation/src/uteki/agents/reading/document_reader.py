"""Read-only, single-index navigation. No model, network or semantic inference."""
import hashlib
import json
from pathlib import Path
from uteki.agents.reading.reading_groups import build_reading_groups, VERSION


def sha(data):
    return hashlib.sha256(data).hexdigest()


class DocumentReader:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.manifest = json.loads((self.folder / 'manifest.json').read_text())
        for name in ('index.json', 'blocks.jsonl'):
            if sha((self.folder / name).read_bytes()) != self.manifest['artifacts'][name]['sha256']:
                raise ValueError('Artifact hash mismatch: ' + name)
        self.index = json.loads((self.folder / 'index.json').read_text())
        self.blocks = [json.loads(line) for line in (self.folder / 'blocks.jsonl').read_text().splitlines()]
        self.positions = {b['block_id']: i for i, b in enumerate(self.blocks)}
        self.nodes = {n['node_id']: n for n in self.index['nodes']}
        self.groups = build_reading_groups(self.blocks, self.index['nodes'])
        # Transcript source blocks remain atomic; reading contexts join the whole
        # exchange, including the analyst's question and all management answers.
        if self.index['form_type'] == 'EARNINGS_CALL':
            self.groups = []
            for node in self.index['nodes']:
                # Prepared remarks can be long: read requested paragraphs with
                # speaker metadata, not the entire speech. Q&A stays indivisible.
                if node['kind'] != 'exchange':
                    continue
                lo, hi = self._range(node['node_id'])
                self.groups.append({'group_id':node['node_id'],'kind':node['kind'],
                    'block_ids':[b['block_id'] for b in self.blocks[lo:hi]],'item_ids':[],
                    'rule':'Full speaker turn or full analyst Q&A exchange; no semantic inference'})

    def outline(self):
        return {'index_id': self.index['index_id'], 'status': self.manifest['status'],
                'nodes': self.index['nodes'], 'diagnostics': self.index['diagnostics']}

    def _range(self, node_id):
        n = self.nodes[node_id]
        return self.positions[n['start_block_id']], self.positions[n['end_block_id']] + 1

    def search(self, node_id, query, offset=0, limit=8):
        """Case-insensitive literal phrase search, in source order, not relevance ranking."""
        if not query.strip() or offset < 0 or not 1 <= limit <= 20:
            raise ValueError('Nonempty query, offset >= 0, limit 1..20 required')
        start, end = self._range(node_id)
        hits = [b for b in self.blocks[start:end] if query.casefold() in b['text'].casefold()]
        previews = []
        for b in hits[offset:offset + limit]:
            pos = b['text'].casefold().find(query.casefold())
            previews.append({'block_id': b['block_id'], 'type': b['type'],
                             'reported_page': b['reported_page'],
                             **({k:b[k] for k in ('pdf_page','speaker','speaker_role','exchange_id')} if 'pdf_page' in b else {}),
                             'preview': b['text'][max(0, pos - 80):pos + 240]})
        return {'index_id': self.index['index_id'], 'node_id': node_id, 'total': len(hits),
                'hits': previews, 'next_offset': offset + limit if offset + limit < len(hits) else None}

    def read(self, node_id, start_block_id, count=8):
        """Full blocks; explicit continuation, never silently truncate a table or paragraph."""
        if not 1 <= count <= 12:
            raise ValueError('count must be 1..12')
        lo, hi = self._range(node_id)
        start = self.positions[start_block_id]
        if not lo <= start < hi:
            raise ValueError('Block outside selected node')
        end = min(start + count, hi)
        eligible_groups = []
        for group in self.groups:
            gs = self.positions[group['block_ids'][0]]
            ge = self.positions[group['block_ids'][-1]] + 1
            if lo <= gs and ge <= hi:
                eligible_groups.append((group, gs, ge))
        # A later group can expand into an earlier one (for example, a table
        # note introducing a list). Reach the complete overlapping context
        # regardless of group order, while preserving the selected node.
        while True:
            previous_range = start, end
            for _, gs, ge in eligible_groups:
                if gs < end and ge > start:
                    start, end = min(start, gs), max(end, ge)
            if (start, end) == previous_range:
                break
        matched_groups = [group for group, gs, ge in eligible_groups if gs < end and ge > start]
        return {'index_id': self.index['index_id'], 'node_id': node_id,
                'reading_group_version': VERSION, 'reading_groups': matched_groups,
                'expansion_note': 'Complete list/table/turn/Q&A context may exceed requested count; original blocks unchanged.',
                'blocks': self.blocks[start:end],
                'previous_block_id': self.blocks[start - 1]['block_id'] if start > lo else None,
                'next_block_id': self.blocks[end]['block_id'] if end < hi else None,
                'context_note': 'Check preceding heading/introduction and following list continuation; tables retain cells and XBRL.'}
