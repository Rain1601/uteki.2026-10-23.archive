"""Host entry point for report tools and the dedicated Uteki report Agent."""
import argparse
import asyncio
import json
from pathlib import Path

from uteki.infrastructure.investment_reports.fxbaogao import FxBaogaoService


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', required=True, type=Path)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--credential-file', type=Path)
    parser.add_argument('--max-downloads', type=int, default=0,
                        help='Persistent workspace cap on new download attempts, not provider balance')
    sub = parser.add_subparsers(dest='command', required=True)
    tool = sub.add_parser('tool')
    tool.add_argument('--requests', required=True, type=Path,
                      help='JSON list of ordered tool calls; every call goes through the same service')
    imported = sub.add_parser('import-pdf')
    imported.add_argument('--report-id', type=int, required=True)
    imported.add_argument('--pdf', type=Path, required=True)
    imported.add_argument('--sha256', required=True)
    agent = sub.add_parser('agent')
    agent.add_argument('--question-file', type=Path, required=True)
    agent.add_argument('--output', type=Path, required=True)
    agent.add_argument('--skill', type=Path, required=True)
    agent.add_argument('--model', required=True)
    agent.add_argument('--provider', required=True, choices=['aihubmix', 'deepseek'])
    agent.add_argument('--model-credentials-root', required=True, type=Path)
    agent.add_argument('--model-budget', required=True, type=Path)
    agent.add_argument('--model-budget-usd', required=True)
    args = parser.parse_args(argv)
    try:
        service = FxBaogaoService(scope=json.loads(args.scope.read_text()), workspace=args.workspace,
            credential_file=args.credential_file, max_downloads=args.max_downloads)
        if args.command == 'import-pdf':
            result = service.import_pdf(args.report_id, args.pdf, args.sha256)
        elif args.command == 'tool':
            calls = json.loads(args.requests.read_text())
            if not isinstance(calls, list) or not 1 <= len(calls) <= 10:
                raise ValueError('invalid_tool_sequence')
            result = {'status': 'completed', 'results': []}
            for call in calls:
                item = service.invoke(call['tool'], call['arguments'])
                result['results'].append(item)
                if item['status'] == 'error':
                    result['status'] = 'failed'
                    break
        else:
            from uteki.agents.investment_reports.agent import run_agent
            from uteki.agents.runtime.local_credentials import load_provider_key
            from uteki.agents.runtime.model_factory import model_adapter
            from uteki.agents.runtime.call_costs import MeteredModel, pricing_snapshot, summarize
            from uteki.agents.runtime.run_budget import RunBudget
            load_provider_key(args.model_credentials_root, args.provider)
            pricing = pricing_snapshot(args.provider, args.model)
            if pricing is None:
                raise ValueError('known_model_pricing_required')
            # Meter files live next to the immutable Agent output, never inside a pre-created output.
            meter_folder = args.output.parent / (args.output.name + '-calls')
            meter_folder.mkdir(parents=True, exist_ok=False)
            budget = RunBudget(args.model_budget, args.model_budget_usd)
            model = MeteredModel(model_adapter(args.model, args.provider), meter_folder,
                'investment_reports', args.provider, args.model, pricing, budget=budget)
            result = asyncio.run(run_agent(service, model=model, skill_path=args.skill,
                question=args.question_file.read_text(), output=args.output))
            (args.output / 'costs.json').write_text(json.dumps(summarize(meter_folder), indent=2))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result.get('status') in ('failed', 'error') else 0
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
