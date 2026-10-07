#!/usr/bin/env python3
"""One explicitly scoped real Agent call, or a no-network preflight."""
import argparse
import asyncio
import json
from pathlib import Path

from uteki.agents.business_map.product_run import prepare, execute
from uteki.agents.business_map.product_contract import DRAFT_VERSION, LEGACY_DRAFT_VERSION, BUSINESS_DRAFT_VERSION, BUSINESS_DRAFT_VERSIONS
from uteki.agents.business_map.product_wire import FULL, COMPACT


def save_preflight(prepared, output):
    """Keep the exact reviewable request; changed inputs need a new filename."""
    output = Path(output)
    prefix = output.stem
    json_bytes = lambda value: (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    files = {
        output: json_bytes(prepared['manifest']),
        output.with_name(prefix + '.request.json'): prepared['request'],
        output.with_name(prefix + '.skill.md'): prepared['skill'].encode('utf-8'),
        output.with_name(prefix + '.output-schema.json'): json_bytes(prepared['schema']),
        output.with_name(prefix + '.source-wire.json'): prepared['kwargs']['input'].encode('utf-8'),
    }
    for path, raw in files.items():
        if path.exists() and (not path.is_file() or path.read_bytes() != raw):
            raise ValueError('preflight_changed_use_new_path: ' + str(path))
    output.parent.mkdir(parents=True, exist_ok=True)
    for path, raw in files.items():
        if not path.exists():
            with path.open('xb') as stream:
                stream.write(raw)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('root','packet','skill'):
        p.add_argument('--'+name, type=Path, required=True)
    for name in ('company-id','document-id','period-end','model','effort'):
        p.add_argument('--'+name, required=True)
    p.add_argument('--max-tokens', type=int, required=True)
    p.add_argument('--timeout-seconds', type=int, required=True)
    p.add_argument('--stream', action='store_true',
                   help='Receive the model response as a stream and assemble it before validation.')
    p.add_argument('--contract-version', choices=(LEGACY_DRAFT_VERSION, DRAFT_VERSION, *BUSINESS_DRAFT_VERSIONS), default=DRAFT_VERSION)
    p.add_argument('--wire-mode', choices=(FULL, COMPACT), default=FULL,
                   help='Use full evidence by default; compact-v1 keeps source text and grid in a verified reading projection.')
    p.add_argument('--preflight-output', type=Path, required=True)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--output', type=Path)
    p.add_argument('--observation-root', type=Path)
    p.add_argument('--budget-limit-usd')
    a=p.parse_args()
    prepared = prepare(root=a.root, packet_path=a.packet, skill_path=a.skill,
        company_id=a.company_id, document_id=a.document_id, period_end=a.period_end,
        model=a.model, effort=a.effort, max_tokens=a.max_tokens, timeout_seconds=a.timeout_seconds,
        stream=a.stream, contract_version=a.contract_version, wire_mode=a.wire_mode)
    save_preflight(prepared, a.preflight_output)
    if a.execute:
        if not all((a.output,a.observation_root,a.budget_limit_usd)):
            p.error('--execute requires --output --observation-root --budget-limit-usd')
        from uteki.agents.runtime.local_credentials import load_provider_key
        load_provider_key(a.root, 'aihubmix')
        result=asyncio.run(execute(prepared,root=a.root,output=a.output,
            observation_root=a.observation_root,budget_limit_usd=a.budget_limit_usd))
        print(json.dumps({k:result.get(k) for k in ('status','trace_id','counts','budget')}, ensure_ascii=False))
    else:
        print(json.dumps(prepared['manifest'], ensure_ascii=False, indent=2))

if __name__=='__main__':
    main()
