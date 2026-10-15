"""Read actual source evidence from a verified published HTML build."""
from __future__ import annotations

from ..catalog.database import read_regular
from ..content.publication import validated_json
from ..contracts.common import CatalogError,digest
from ..contracts.evidence import HtmlBlock,HtmlEvidenceRef,HtmlImage,HtmlSchema,HtmlSection,HtmlTable,InlineRecord
from ..build.dom import SourceDOM,normalize
from ..build.pipeline import recipe_config


class HtmlReader:
    """A verified immutable byte view. Construct again to audit current disk state.

    No online fallback, latest-version selection or untrusted XPath evaluation.
    All visible inventory items carry a full version reference when returned.
    """
    def __init__(self,catalog,reference):
        manifest=catalog.read_published(reference)
        if manifest.schema_version!='uteki-html-build-v1':
            raise CatalogError('UNSUPPORTED_FORMAT','HTML reading requires an HTML build; old artifacts remain readable through Catalog')
        self.reference=manifest.asset_ref
        self.inputs=catalog.content.read_manifest(manifest.input_manifest)
        raw=catalog.content.read_object(self.inputs.main)
        rules=recipe_config(catalog.content,manifest.recipe)
        self._dom=SourceDOM(raw,encoding=rules['encoding'])
        payloads={}
        for item in manifest.files:
            content=read_regular(catalog.root/'assets'/reference.asset_id/'builds'/reference.build_id/item.path)
            if len(content)!=item.object_ref.byte_length or digest(content)!=item.object_ref.sha256:
                raise CatalogError('PUBLICATION_INVALID','artifact changed while opening reader')
            payloads[item.path]=content
        self._schema=validated_json(HtmlSchema,payloads['asset-schema.json'])
        self._items={}
        for name,model in [('blocks',HtmlBlock),('sections',HtmlSection),('tables',HtmlTable),('records',InlineRecord),('images',HtmlImage)]:
            self._items[name]=tuple(validated_json(model,line) for line in payloads[name+'.jsonl'].splitlines())
        self._blocks={item.id:item for item in self._items['blocks']}
        self._records={item.id:item for item in self._items['records']}
        self._cells={cell.id:(table,cell) for table in self._items['tables'] for cell in table.cells}

    def inventory(self):
        # Return detached values, not mutable containers used by later reads.
        return dict(asset_ref=self.reference.model_dump(mode='json'),schema=self._schema.model_dump(mode='json'),
                    **{name:[item.model_dump(mode='json') for item in values] for name,values in self._items.items()})

    def _source(self,locator):
        node,text=self._dom.resolve(locator)
        return dict(source_object=self.inputs.main.model_dump(mode='json'),source_url=self.inputs.main_source_url,
                    locator=locator.model_dump(mode='json'),text=text,
                    raw_node_text=normalize(node.text_content()),html=self._dom.snippet(node))

    def _table_context(self,table):
        return dict(table=table.model_dump(mode='json'),
            adjacent_blocks=[self._blocks[identity].model_dump(mode='json') for identity in table.context_block_ids])

    def read(self,evidence:HtmlEvidenceRef):
        evidence=HtmlEvidenceRef.model_validate(evidence)
        if evidence.asset_ref!=self.reference:
            raise CatalogError('IDENTITY_CONFLICT','evidence belongs to a different explicit build')
        context={}
        if evidence.kind=='block':
            if evidence.field!='text':raise CatalogError('INVALID_LOCATOR','block supports text only')
            item=self._blocks.get(evidence.item_id)
            if item is None:raise CatalogError('NOT_FOUND','block does not exist in this build')
            value=item.text
            order=self._items['blocks'];index=next(i for i,b in enumerate(order) if b.id==item.id)
            context['adjacent_blocks']=[b.model_dump(mode='json') for b in order[max(0,index-2):index+3] if b.id!=item.id]
        elif evidence.kind=='table_cell':
            if evidence.field!='text':raise CatalogError('INVALID_LOCATOR','table cell supports text only')
            pair=self._cells.get(evidence.item_id)
            if pair is None:raise CatalogError('NOT_FOUND','table cell does not exist in this build')
            table,item=pair;value=item.text;context=self._table_context(table)
            context['footnotes']=[dict(dom_path=path,html=self._dom.snippet(self._dom.paths[path]),
                text=self._dom.text(self._dom.paths[path])) for path in item.footnote_paths]
        else:
            if evidence.field not in {'value_decimal','raw_value'}:
                raise CatalogError('INVALID_LOCATOR','record supports raw_value or value_decimal')
            item=self._records.get(evidence.item_id)
            if item is None:raise CatalogError('NOT_FOUND','record does not exist in this build')
            if evidence.field=='value_decimal' and item.status!='parsed':
                raise CatalogError('CONTENT_NOT_READY','numeric value is '+item.status+': '+'; '.join(item.issues))
            value=getattr(item,evidence.field)
            context['record']=item.model_dump(mode='json')
            for key,path in [('xbrl_context',item.context_path),('xbrl_unit',item.unit_path)]:
                context[key]=dict(dom_path=path,html=self._dom.snippet(self._dom.paths[path])) if path else None
            enclosing=[t for t in self._items['tables'] if item.locator.dom_path.startswith(t.locator.dom_path+'/')]
            if enclosing:
                context.update(self._table_context(max(enclosing,key=lambda t:len(t.locator.dom_path))))
        source=self._source(item.locator)
        if evidence.kind!='record_field' and value!=source['text']:
            raise CatalogError('INVALID_LOCATOR','content differs from its frozen source range')
        return dict(evidence_ref=evidence.model_dump(mode='json'),value=value,source=source,context=context)
