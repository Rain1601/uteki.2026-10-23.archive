"""Render one configured Skill without model calls or SDK execution."""
import argparse
import json
from pathlib import Path

from uteki.data_platform.agent.skills import get_skill


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-root', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--sdk', required=True)
    parser.add_argument('--model-version')
    parser.add_argument('--sdk-version')
    parser.add_argument('--language', default='zh-CN')
    parser.add_argument('--output', type=Path, help='New absolute directory; omit to print the complete Skill')
    args = parser.parse_args()
    skill = get_skill(args.name, config_root=args.config_root, model=args.model, sdk=args.sdk,
        model_version=args.model_version, sdk_version=args.sdk_version, params={'output_language': args.language})
    if args.output is not None:
        target = skill.write_to(args.output)
        print(json.dumps(skill.metadata() | {'directory': str(target)}, ensure_ascii=False, indent=2))
    else:
        print(skill.content, end='')


if __name__ == '__main__':
    main()
