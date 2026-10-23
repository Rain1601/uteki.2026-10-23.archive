"""Build and describe HTML artifacts using the existing freeze/publication protocol."""
from __future__ import annotations

import json

from ..contracts.assets import ArtifactFile, BuildManifest, BuildRecipe
from ..contracts.common import CatalogError, canonical, digest
from ..contracts.content import MissingResource, ObjectRef
from ..contracts.evidence import HtmlReadiness, HtmlSchema
from .html import CANDIDATE_VERSION, PROCESSOR_VERSION, parse_html

HTML_FILES = {'sections.jsonl','blocks.jsonl','tables.jsonl','records.jsonl','images.jsonl','quality.json','asset-schema.json'}


# 冻结 HTML 处理版本和显式规则配置；配置存入对象仓库，配方引用其不可变字节。
def html_recipe(catalog, *, encoding: str, form_type: str, profile_ref: str, taxonomy_ref: str):
    if encoding != 'utf-8' or not isinstance(form_type,str) or not form_type.strip():
        raise CatalogError('INVALID_ARGUMENT','supported explicit encoding and material form required')
    config=dict(capabilities=['original','text','outline','tables','inline_facts'],targets=['document'],models=[],
        rules=dict(encoding=encoding,form_type=form_type,candidate_version=CANDIDATE_VERSION,normalization_version='visible_text_v1'))
    return BuildRecipe(processor_version=PROCESSOR_VERSION,config=catalog.content.put_object(canonical(config)),
                       profile_ref=profile_ref,taxonomy_ref=taxonomy_ref)


# 读取并核验受支持的版本化配方，只接受精确约定的能力、规则和空模型列表。
def recipe_config(content, recipe):
    recipe=BuildRecipe.model_validate(recipe)
    if recipe.processor_version not in {'uteki-html-parser-v1',PROCESSOR_VERSION}:
        raise CatalogError('UNSUPPORTED_PROCESSOR','unknown HTML processor version')
    raw=content.read_object(recipe.config)
    config=json.loads(raw)
    if not isinstance(config,dict) or canonical(config)!=raw or set(config)!={'capabilities','targets','models','rules'}:
        raise CatalogError('INVALID_ARGUMENT','invalid HTML recipe configuration')
    if config['capabilities']!=['original','text','outline','tables','inline_facts'] or config['targets']!=['document'] or config['models']!=[]:
        raise CatalogError('INVALID_ARGUMENT','unsupported HTML recipe capabilities/targets/models')
    rules=config['rules']
    if (not isinstance(rules,dict) or set(rules)!={'encoding','form_type','candidate_version','normalization_version'}
        or rules['encoding']!='utf-8' or rules['candidate_version']!=CANDIDATE_VERSION or rules['normalization_version']!='visible_text_v1'
        or not isinstance(rules['form_type'],str) or not rules['form_type'].strip()):
        raise CatalogError('INVALID_ARGUMENT','unknown HTML parsing rules')
    return rules


# 由冻结原件与配方确定性生成全部产物，并依据实际覆盖、缺口和版本规则声明能力状态。
def artifact_payloads(content, *, reference, inputs, recipe):
    rules=recipe_config(content,recipe)
    legacy_v1=recipe.processor_version=='uteki-html-parser-v1'
    parsed=parse_html(content.read_object(inputs.main),inputs,encoding=rules['encoding'],form_type=rules['form_type'],legacy_v1=legacy_v1)
    counts=parsed.quality.counts
    missing=any(isinstance(r,MissingResource) for r in inputs.resources)
    gaps=list(parsed.quality.issues)
    if missing:gaps.append('input_resources_missing')
    if not parsed.sections:gaps.append('no_supported_outline')
    if not parsed.tables:gaps.append('no_tables_in_supported_content')
    if not parsed.records:gaps.append('no_inline_facts_in_source')
    # 原件、正文、提纲、表格和数值事实分项判断就绪度；例如 DOM 修复会影响正文/表格可靠性。
    html_recovered=not legacy_v1 and any(issue.startswith('html_recovery:') for issue in parsed.quality.issues)
    table_gap=html_recovered or not legacy_v1 and any(issue.startswith('unresolved_table_link:') for issue in parsed.quality.issues)
    readiness=HtmlReadiness(original='partial' if missing else 'ready',text='ready' if counts['unexplained_omissions']==0 and not html_recovered else 'partial',
        outline='partial' if parsed.sections and any(s.basis=='inferred_style' for s in parsed.sections) else 'ready' if parsed.sections else 'not_ready',
        tables='partial' if parsed.tables and table_gap else 'ready' if parsed.tables else 'not_ready',inline_facts='partial' if counts['facts_unsupported'] or counts['facts_invalid'] else 'ready' if parsed.records else 'not_ready',
        images='not_ready',records='not_ready',search='not_ready')
    schema=HtmlSchema(schema_version='uteki-asset-schema-html-v1',asset_ref=reference,processor_version=recipe.processor_version,
        content_readiness=readiness,published_readiness=readiness,gaps=tuple(gaps),
        description='Frozen HTML text, source tables and inline numeric facts. Explicit unsupported facts and resource gaps retained; no images understanding, structured query or search index.')
    files={name+'.jsonl':b''.join(item.canonical_bytes()+b'\n' for item in getattr(parsed,name))
           for name in ('sections','blocks','tables','records','images')}
    # 旧处理器版本保持原字节格式，移除当时不存在的 footnote_links 字段以支持历史验证。
    if legacy_v1:
        values=[table.model_dump(mode='json') for table in parsed.tables]
        for table in values:
            for cell in table['cells']:cell.pop('footnote_links')
        files['tables.jsonl']=b''.join(canonical(table)+b'\n' for table in values)
    files.update({'quality.json':parsed.quality.canonical_bytes(),'asset-schema.json':schema.canonical_bytes()})
    return files


# 组装产物字节及逐文件哈希清单；此阶段生成候选内容，发布交给 Publication。
def build_bundle(catalog, build):
    reference=catalog.asset_ref(build)
    input_ref=ObjectRef.model_validate_json(build['input_ref'])
    recipe=BuildRecipe.model_validate_json(build['recipe'])
    inputs=catalog.content.read_manifest(input_ref)
    files=artifact_payloads(catalog.content,reference=reference,inputs=inputs,recipe=recipe)
    manifest=BuildManifest(schema_version='uteki-html-build-v1',asset_ref=reference,input_manifest=input_ref,recipe=recipe,
        files=tuple(ArtifactFile(path=name,object_ref=ObjectRef(sha256=digest(raw),byte_length=len(raw))) for name,raw in files.items()))
    return files,manifest


# 串联构建登记、解析、暂存和发布，复用已发布结果；封存后的中断交给显式恢复协议。
def build_html(catalog, *, snapshot_id, representation_id, recipe, run_id, retry_of_build_id=None, checkpoint=None):
    from ..content.publication import Publication
    check = checkpoint or (lambda phase: None)
    check('before_build_registration')
    recipe_config(catalog.content,recipe)
    build=catalog.begin_build(snapshot_id=snapshot_id,representation_id=representation_id,recipe=recipe,
                             run_id=run_id,retry_of_build_id=retry_of_build_id)
    if build['status']=='published':
        reference=catalog.asset_ref(build)
        catalog.read_published(reference)
        return reference
    if build['manifest_ref'] is not None:
        raise CatalogError('RECOVERY_REQUIRED','sealed build requires explicit publication/recovery')
    try:
        files,manifest=build_bundle(catalog,build)
        check('build_parsed')
        publisher=Publication(catalog,checkpoint=checkpoint)
        publisher.stage(build['build_id'],files=files,manifest=manifest)
        return publisher.publish(build['build_id'])
    except Exception as error:
        current=catalog.get_build(build['build_id'])
        # A moved/sealed candidate is owned by the existing explicit recovery
        # protocol. Never turn an uncertain publication result into a failed one.
        # 仅尚未封存且提交结果明确的失败可直接终结；已有候选或提交不确定时保留恢复所需状态。
        if current['status']=='staging' and current['manifest_ref'] is None and not catalog.database.head_uncertain:
            catalog.fail_build(build['build_id'],failure_code=getattr(error,'code','PARSE_FAILED'))
        raise
