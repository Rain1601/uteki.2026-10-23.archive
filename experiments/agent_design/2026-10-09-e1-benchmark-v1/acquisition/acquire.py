"""Use the system acquisition entry point with explicit annual range; no models."""
import json
from pathlib import Path

from uteki.infrastructure.document_sources.company_acquisition import prepare_sources
from uteki.infrastructure.document_sources.sec_settings import resolve_sec_contact

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent


def main():
    config = json.loads((HERE/'msft-fy2024-fy2025.config.json').read_text())
    contact, origin = resolve_sec_contact(settings_root=ROOT)
    if not contact:
        raise ValueError('missing real UTEKI_SEC_USER_AGENT; no network request sent')
    config.update(sec_user_agent=contact, sec_contact_origin=origin)
    result = prepare_sources(config, HERE/'workspace')
    print(json.dumps({
        'status': result['status'], 'requests': result['requests'],
        'manifest_path': result['manifest_path'],
        'documents': [{'source_id': d['source_id'], 'period_end': d['period_end'],
                       'form': d['form'], 'acquisition': d['acquisition']} for d in result['documents']],
        'gaps': result['gaps'],
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
