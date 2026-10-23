"""Resolve a business Skill using explicit configuration; no model or SDK calls."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from string import Template
from types import MappingProxyType
from typing import Mapping


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def _text(value, field):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f'{field} must be nonblank text without surrounding whitespace')
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate mapping key: {key}')
        result[key] = value
    return result


def _path(root, relative):
    relative = _text(relative, 'relative path')
    path = PurePosixPath(relative)
    if path.is_absolute() or '\\' in relative or any(p in {'', '.', '..'} for p in relative.split('/')):
        raise ValueError('Skill path must be a normalized relative path')
    target = root.joinpath(*path.parts)
    for parent in (target, *target.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('Skill symlinks are not supported')
    resolved = target.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError('Skill path escapes configuration root')
    return resolved


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    content: str
    files: Mapping[str, bytes]
    selection: Mapping
    sha256: str

    def metadata(self):
        return dict(self.selection) | {'name': self.name, 'sha256': self.sha256}

    def write_to(self, directory: Path) -> Path:
        """Materialize one frozen bundle in a new directory; never overwrite files."""
        directory = Path(directory)
        if not directory.is_absolute():
            raise ValueError('explicit absolute Skill directory required')
        # The caller owns the isolated parent; reject symlink ancestors too.
        if any(p.is_symlink() for p in (directory, *directory.parents)):
            raise ValueError('Skill output must not traverse symlinks')
        directory.mkdir(parents=True, exist_ok=False)
        for name, content in {'SKILL.md': self.content.encode(), **self.files}.items():
            path = directory/name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(content)
        return directory


def get_skill(name: str, *, config_root: Path, model: str, sdk: str,
              model_version: str | None = None, sdk_version: str | None = None,
              params: Mapping[str, str] | None = None,
              available_tools: tuple[str, ...] | None = None) -> LoadedSkill:
    """Exact versions -> model/SDK -> SDK -> default; errors never fall back.

    Versions are literal provider/runtime identifiers, not inferred ranges.
    ``available_tools`` is host-supplied context, never a permission grant.
    """
    if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name):
        raise ValueError('invalid Skill name')
    _text(model, 'model'); _text(sdk, 'sdk')
    for label, version in (('model_version', model_version), ('sdk_version', sdk_version)):
        if version is not None:
            _text(version, label)
            if version == '*':
                raise ValueError('runtime version cannot be a wildcard; use None when unknown')
    if not str(config_root).strip():
        raise ValueError('explicit configuration root required')
    root = Path(config_root).resolve(strict=True)
    package = _path(root, f'skills/{name}')
    sources = {}

    def read(relative):
        raw = _path(package, relative).read_bytes()
        sources[relative] = hashlib.sha256(raw).hexdigest()
        return raw.decode('utf-8')

    mapping = json.loads(read('mapping.json'), object_pairs_hook=_pairs)
    if not isinstance(mapping, dict) or set(mapping) != {'version', 'default', 'sdk_defaults', 'bindings'}:
        raise ValueError('mapping requires version, default, sdk_defaults and bindings only')
    _text(mapping['version'], 'mapping version')
    default, sdks, bindings = mapping['default'], mapping['sdk_defaults'], mapping['bindings']
    if not isinstance(sdks, dict) or not isinstance(bindings, list):
        raise ValueError('invalid SDK defaults or bindings')
    reserved = {'base_skill', 'model_guidance', 'tool_guidance', 'model', 'sdk', 'model_version', 'sdk_version'}

    def entry(value, *, binding=False):
        allowed = {'guidance', 'params'} | ({'model', 'sdk', 'model_version', 'sdk_version'} if binding else set())
        if not isinstance(value, dict) or 'guidance' not in value or set(value) - allowed:
            raise ValueError('invalid guidance entry')
        _text(value['guidance'], 'guidance')
        parameters = value.get('params', {})
        if not isinstance(parameters, dict):
            raise ValueError('params must be an object')
        for key, value in parameters.items():
            if not isinstance(key, str) or not key.isidentifier() or key in reserved:
                raise ValueError('invalid or reserved Skill parameter')
            _text(value, key)
        return parameters

    defaults = entry(default)
    declared = set(defaults)
    for key, item in sdks.items():
        _text(key, 'SDK key')
        if set(entry(item)) - declared:
            raise ValueError('SDK default contains undeclared parameters')
    indexed = {}
    for item in bindings:
        if set(entry(item, binding=True)) - declared:
            raise ValueError('binding contains undeclared parameters')
        key = tuple(_text(item.get(k), k) for k in ('model', 'sdk', 'model_version', 'sdk_version'))
        if '*' in key[:2] or (key[2] == '*') != (key[3] == '*'):
            raise ValueError('only paired version wildcards are supported')
        if key in indexed:
            raise ValueError('duplicate model/SDK/version binding')
        indexed[key] = item
    choices = [('exact', indexed.get((model, sdk, model_version, sdk_version))),
               ('model_sdk', indexed.get((model, sdk, '*', '*'))),
               ('sdk_default', sdks.get(sdk)), ('default', default)]
    level, selected = next((level, item) for level, item in choices if item is not None)
    supplied = dict(params) if params is not None else {}
    if set(supplied) - declared:
        raise ValueError('unknown or protected Skill parameter')
    values = {**defaults, **sdks.get(sdk, {}).get('params', {}), **selected.get('params', {}), **supplied}
    for key, value in values.items():
        _text(value, key)
    values.update(model=model, sdk=sdk, model_version=model_version or 'unknown', sdk_version=sdk_version or 'unknown')
    base = read('SKILL.md')
    frontmatter = base.split('---', 2)
    if (not base.startswith('---\n') or len(frontmatter) != 3
            or not re.search(r'^name:\s*'+re.escape(name)+r'\s*$', frontmatter[1], re.M)):
        raise ValueError('Skill frontmatter name differs from requested Skill')
    guidance = Template(read(selected['guidance'])).substitute(values)
    tools = None if available_tools is None else sorted({_text(t, 'tool name') for t in available_tools})
    tool_guidance = ('使用宿主实际注册的工具；本指导不授予新的工具权限。' if tools is None else
                     '本次宿主注册的业务工具：'+', '.join(tools)+'。未列出的业务工具不可调用。')
    template = Template(read('SKILL.template.md'))
    if not template.is_valid() or set(template.get_identifiers()) != {'base_skill', 'model_guidance', 'tool_guidance'}:
        raise ValueError('Skill template must contain exactly the three declared slots')
    content = template.substitute(base_skill=base.rstrip(), model_guidance=guidance.rstrip(), tool_guidance=tool_guidance)
    files = {}
    for folder in ('references', 'scripts'):
        directory = package/folder
        if directory.is_symlink():
            raise ValueError('Skill resources cannot be symlinks')
        if directory.exists():
            for path in sorted(directory.rglob('*')):
                if '__pycache__' in path.parts:
                    continue
                relative = path.relative_to(package).as_posix()
                checked = _path(package, relative)
                if checked.is_file():
                    files[relative] = checked.read_bytes()
                    sources[relative] = hashlib.sha256(files[relative]).hexdigest()
    digest = hashlib.sha256(_json({'content': content, 'files': {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}})).hexdigest()
    selection = dict(model=model, sdk=sdk, model_version=model_version, sdk_version=sdk_version,
        match=level, guidance=selected['guidance'], mapping_version=mapping['version'],
        status='unverified', source_sha256=hashlib.sha256(_json(sources)).hexdigest())
    return LoadedSkill(name, content, MappingProxyType(files), MappingProxyType(selection), digest)
