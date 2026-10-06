"""Read-only project declarations and evidence inventory; no acceptance evaluation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
CHECKBOX = re.compile(r'\[([ xX])\]\s*([^|]+)')
LINK = re.compile(r'(?<!!)\[[^\]]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+["\'][^\n]*?["\'])?\s*\)')
STATUS = re.compile(r'^\s*(?:[-*]\s+)?(?:\*\*)?(?:状态|当前状态|Status)(?:\*\*)?\s*[:：]', re.I)


def git(root, *args):
    result = subprocess.run(['git', '--no-optional-locks', '-C', str(root), *args], shell=False,
                            capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise ValueError('无法读取 Git 仓库：' + result.stderr.strip())
    return result.stdout.rstrip('\n')


def contained(root, path):
    return path.resolve().is_relative_to(root)


def read_document(root, path):
    relative = path.relative_to(root).as_posix()
    if not contained(root, path):
        return {'path': relative, 'status': 'outside_root', 'title': None, 'declared_status': []}
    if not path.is_file():
        return {'path': relative, 'status': 'missing', 'title': None, 'declared_status': []}
    lines = path.read_text(encoding='utf-8').splitlines()
    title = next(({'line': i, 'text': line.lstrip('#').strip()}
                  for i, line in enumerate(lines, 1) if re.match(r'^#{1,6}\s+', line)), None)
    statuses = [{'line': i, 'text': line.strip()} for i, line in enumerate(lines, 1) if STATUS.match(line)]
    return {'path': relative, 'status': 'exists', 'title': title, 'declared_status': statuses}


def inspect_project(root, limit=5):
    if limit < 1:
        raise ValueError('limit 必须是正整数')
    root = Path(root).resolve()
    head = git(root, 'rev-parse', 'HEAD')
    branch = git(root, 'rev-parse', '--abbrev-ref', 'HEAD')
    changes = git(root, 'status', '--porcelain=v1', '--untracked-files=normal')
    commits = []
    for line in git(root, 'log', f'-{limit}', '--format=%H%x09%s').splitlines():
        revision, subject = line.split('\t', 1)
        commits.append({'revision': revision, 'subject': subject})
    todo = root / 'TODO.md'
    tasks, links = [], []
    todo_status = 'outside_root' if not contained(root, todo) else 'exists' if todo.is_file() else 'missing'
    if todo_status == 'exists':
        for number, line in enumerate(todo.read_text(encoding='utf-8').splitlines(), 1):
            for match in CHECKBOX.finditer(line):
                tasks.append({'line': number, 'text': match[2].strip(),
                              'declared': 'checked' if match[1].lower() == 'x' else 'unchecked'})
            for match in LINK.finditer(line):
                target = match[1] or match[2]
                parsed = urlsplit(target)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                path = todo.parent / unquote(parsed.path)
                outside = not contained(root, path)
                exists = False if outside else path.exists()
                links.append({'line': number, 'target': target,
                              'status': 'outside_root' if outside else 'exists' if exists else 'missing',
                              'evidence_exists': None if outside else exists})
    candidates = {root / 'docs/ROADMAP.zh-CN.md'}
    docs = root / 'docs'
    if contained(root, docs) and docs.is_dir():
        candidates.update(p for p in docs.rglob('*.md')
                          if any(word in p.name.upper() for word in ('PLAN', 'SCOPE', 'ROADMAP')))
    for folder in ('openspec/specs', 'openspec/changes'):
        directory = root / folder
        if contained(root, directory) and directory.is_dir():
            candidates.update(directory.rglob('*.md'))
    return {'root': str(root), 'verification': 'not_performed',
            'note': '勾选和状态仅为文档声明；文件存在不代表实现、测试或研究验收通过。',
            'git': {'head': head, 'branch': branch, 'working_tree': 'dirty' if changes else 'clean',
                    'status_lines': changes.splitlines(), 'recent_commits': commits},
            'todo': {'path': 'TODO.md', 'status': todo_status, 'tasks': tasks, 'local_links': links},
            'documents': [read_document(root, path) for path in sorted(candidates)]}


def format_report(report):
    state = report['git']
    lines = [f"提交：{state['head'][:12]} · 分支：{state['branch']} · 工作树：{state['working_tree']}",
             '验收：未执行（not_performed）。' + report['note'], '', '近期提交：']
    lines.extend(f"- {row['revision'][:12]} {row['subject']}" for row in state['recent_commits'])
    lines += ['', f"TODO 声明（{report['todo']['status']}）："]
    lines.extend(f"- TODO.md:{row['line']} [{'x' if row['declared'] == 'checked' else ' '}] {row['text']}"
                 for row in report['todo']['tasks'])
    lines += ['', '方案与范围声明：']
    for document in report['documents']:
        lines.append(f"- {document['path']}：{(document['title'] or {}).get('text', document['status'])}")
        lines.extend(f"  {row['line']}：{row['text']}" for row in document['declared_status'])
    links = report['todo']['local_links']
    lines += ['', f"TODO 本地链接：{sum(r['status'] == 'exists' for r in links)}/{len(links)} 存在（未验内容）。"]
    lines.extend(f"- TODO.md:{row['line']} {row['status']}：{row['target']}"
                 for row in links if row['status'] != 'exists')
    return '\n'.join(lines)


def positive(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError('必须是正整数') from error
    if number < 1:
        raise argparse.ArgumentTypeError('必须是正整数')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='只读检查的仓库目录')
    parser.add_argument('--json', action='store_true', help='输出结构化声明和证据存在性')
    parser.add_argument('--limit', type=positive, default=5, help='近期提交数量，正整数（默认 5）')
    parser.add_argument('--check-links', action='store_true', help='TODO 缺失、链接缺失或越界时退出 1')
    args = parser.parse_args(argv)
    try:
        report = inspect_project(args.root, args.limit)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        message = {'error': str(error), 'verification': 'not_performed'}
        print(json.dumps(message, ensure_ascii=False) if args.json else f'检查失败：{error}', file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else format_report(report))
    if args.check_links and (report['todo']['status'] != 'exists' or
                            any(row['status'] != 'exists' for row in report['todo']['local_links'])):
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
