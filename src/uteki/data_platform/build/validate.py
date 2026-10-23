"""Validate actual HTML artifacts against their immutable inputs and recipe."""
from __future__ import annotations

from ..contracts.common import CatalogError
from ..contracts.evidence import HtmlBlock,HtmlImage,HtmlQuality,HtmlSchema,HtmlSection,HtmlTable,InlineRecord
from .pipeline import HTML_FILES,artifact_payloads


# 先验证各产物结构，再从冻结原件与配方重建并逐字节比对，返回核验后的能力 schema。
def validate_html_artifacts(content, manifest, inputs, payloads):
    from ..content.publication import validated_json
    if set(payloads)!=HTML_FILES:
        raise CatalogError('PUBLICATION_INVALID','HTML artifact set differs')
    for name,model in [('sections',HtmlSection),('blocks',HtmlBlock),('tables',HtmlTable),('records',InlineRecord),('images',HtmlImage)]:
        for line in payloads[name+'.jsonl'].splitlines():
            validated_json(model,line)
    schema=validated_json(HtmlSchema,payloads['asset-schema.json'])
    validated_json(HtmlQuality,payloads['quality.json'])
    # Hashes alone only prove transport. Reconstruct from the frozen bytes and
    # supported versioned recipe to verify exact source bindings, tables, facts,
    # exclusions and capability declarations. Independent gold is test-only.
    # 哈希只证明产物没变；同版本重建校验来源绑定与处理结果，仍不替代独立业务答案核验。
    expected=artifact_payloads(content,reference=manifest.asset_ref,inputs=inputs,recipe=manifest.recipe)
    for name in sorted(HTML_FILES):
        if payloads[name]!=expected[name]:
            raise CatalogError('PUBLICATION_INVALID','HTML artifact differs from frozen source/recipe: '+name)
    return schema
