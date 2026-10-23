"""uteki-data: explicit command-line entry for the shared Data core.

`acquire` discovers and freezes official filings without parsing or model
calls. Its arguments and behaviour match the former `uteki-data agent
acquire` (the legacy CLI was archived in S4, 2026-10-23).
"""
import argparse
import json
from pathlib import Path
import sys


# 公司来源只接受显式配置文件，或显式目录中已登记的公司；二者互斥。
def _company_config(args):
    if (args.company is not None) != (args.company_catalog is not None):
        raise ValueError('--company and --company-catalog must be supplied together')
    if args.company is not None:
        from .connectors.company_registry import resolve_company_profile
        return resolve_company_profile(args.company_catalog, args.company)
    return json.loads(args.config.read_text())


# SEC 联系信息按显式参数、环境变量、公司配置、私有 .env 的既有顺序解析，不打印其值。
def run_acquire(args):
    from .connectors.company_acquisition import prepare_sources
    from .connectors.sec_settings import resolve_sec_contact
    config = _company_config(args)
    if not isinstance(config, dict):
        raise ValueError('explicit company configuration object required')
    contact, origin = resolve_sec_contact(explicit=args.sec_user_agent,
        configured=config.get('sec_user_agent'), settings_root=args.settings_root)
    if contact is not None:
        config['sec_user_agent'] = contact
    config['sec_contact_origin'] = origin
    return prepare_sources(config, args.workspace)


def _parser():
    parser = argparse.ArgumentParser(prog='uteki-data', description=__doc__.split('\n')[0])
    commands = parser.add_subparsers(dest='command', required=True)
    acquire = commands.add_parser('acquire', help='discover and download official filings without parsing or model calls')
    source = acquire.add_mutually_exclusive_group(required=True)
    source.add_argument('--config', type=Path, help='versioned company source configuration')
    source.add_argument('--company', help='company name or symbol registered in the explicit catalog')
    acquire.add_argument('--company-catalog', type=Path, help='explicit registered-company catalog with pinned source profiles')
    acquire.add_argument('--workspace', type=Path, required=True, help='original files and immutable acquisition runs')
    acquire.add_argument('--sec-user-agent', help='application and contact identity, or UTEKI_SEC_USER_AGENT')
    acquire.add_argument('--settings-root', type=Path, default=Path.cwd(), help='directory containing private local .env settings')
    return parser


def parse_args(argv=None):
    return _parser().parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        result = run_acquire(args)
    except (ValueError, KeyError, OSError, RuntimeError) as error:
        print(json.dumps({'status': 'failed', 'error_type': type(error).__name__, 'message': str(error)},
                         ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # 有任何来源缺口或失败都返回 2，调用方据 manifest_path 查看逐份状态。
    return 0 if result.get('status') == 'completed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
