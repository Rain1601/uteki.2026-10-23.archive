"""Read-only provider preflight. Never invokes a model or prints credentials."""
import argparse
from datetime import datetime, timezone
import http.client
import json
import os
from pathlib import Path


def credential(name, env_file=None):
    value = os.environ.get(name)
    if not value and env_file:
        for line in Path(env_file).read_text().splitlines():
            key, separator, candidate = line.strip().removeprefix('export ').partition('=')
            if separator and key.strip() == name:
                value = candidate.strip().strip('\"\'')
    if not value or any(c in value for c in '\r\n'):
        raise ValueError('Missing credential: ' + name)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=['deepseek', 'openrouter'], required=True)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--endpoints-only', action='store_true',
                        help='Inspect the two frozen OpenRouter models without inference')
    parser.add_argument('--balance-only', action='store_true')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; retain prior observations')
    host, paths, variable = (
        ('api.deepseek.com', ['/user/balance', '/models'], 'DEEPSEEK_API_KEY')
        if args.provider == 'deepseek' else
        ('openrouter.ai', ['/api/v1/auth/key', '/api/v1/credits', '/api/v1/models'], 'OPENROUTER_API_KEY'))
    if args.endpoints_only:
        if args.balance_only:
            parser.error('Choose one read-only preflight mode')
        if args.provider != 'openrouter':
            parser.error('--endpoints-only requires openrouter')
        paths = ['/api/v1/models/openai/gpt-5.6-luna/endpoints',
                 '/api/v1/models/anthropic/claude-sonnet-5.5/endpoints']
    elif args.balance_only:
        paths = ['/user/balance'] if args.provider == 'deepseek' else ['/api/v1/credits']
    result = dict(provider=args.provider, observed_at=datetime.now(timezone.utc).isoformat(),
                  model_calls=0, observations={})
    try:
        key = credential(variable, args.env_file)
    except ValueError:
        result['error'] = 'credential_unavailable'
    else:
        for path in paths:
            conn = http.client.HTTPSConnection(host, timeout=20)
            try:
                conn.request('GET', path, headers={'Authorization': 'Bearer ' + key})
                response = conn.getresponse()
                raw = response.read(8_000_001)
                if len(raw) > 8_000_000:
                    raise ValueError('preflight_response_too_large')
                result['observations'][path] = dict(status=response.status, body=json.loads(raw))
            except Exception as error:
                result['observations'][path] = dict(error_type=type(error).__name__)
            finally:
                conn.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        os.chmod(args.output, 0o600)
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(provider=args.provider, model_calls=0, output=str(args.output),
        error=result.get('error'), observations={p: {k: v for k, v in item.items() if k != 'body'}
        for p, item in result['observations'].items()})))


if __name__ == '__main__':
    main()
