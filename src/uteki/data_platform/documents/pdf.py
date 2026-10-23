"""Real local Docling PDF conversion into the versioned document store.

No SDK/model API, business facts, or taxonomy is inferred by this adapter.
Download weights explicitly before running; parsing uses local files only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
from io import BytesIO
import json
import os
import re
from pathlib import Path
from pydantic import ValidationError

from ..contracts.common import canonical, digest
from ..contracts.documents import DocumentPackage, Material, TableContent
from .store import DocumentStore, DocumentStoreError
from .directory import build_sections, VERSION as SECTION_VERSION
from .passages import attach_text_lines, build_passages


ADAPTER_VERSION = '4'


def _model_files(root):
    names = {
        'layout': ('docling-project--docling-layout-heron/model.safetensors',),
        'table': ('docling-project--docling-models/model_artifacts/tableformer/accurate/tableformer_accurate.safetensors',),
        'ocr': ('RapidOcr/PP-OCRv6_det_small.onnx', 'RapidOcr/PP-OCRv6_rec_small.onnx',
                'RapidOcr/ch_ppocr_mobile_v2.0_cls_mobile.onnx'),
    }
    identities = {}
    for step, paths in names.items():
        identities[step] = digest(canonical({name: digest((root/name).read_bytes()) for name in paths}))
    return identities


def _native_directory(raw):
    import pypdfium2 as pdfium
    nodes, stack, issues = [], {}, []
    with pdfium.PdfDocument(raw) as pdf:
        for ordinal, bookmark in enumerate(pdf.get_toc()):
            level = bookmark.level
            node_id = f'outline-{ordinal}'
            parent = stack.get(level-1) if level else None
            if level and parent is None:
                issues.append(f'outline_parent_unresolved:{node_id}')
            stack = {k: v for k, v in stack.items() if k < level}
            stack[level] = node_id
            locations = []
            dest = bookmark.get_dest()
            index = dest.get_index() if dest is not None else None
            if index is not None:
                mode, pos = dest.get_view()
                # PDF XYZ and FitH expose a vertical target; other modes retain page only.
                y = pos[1] if mode == 1 and len(pos) >= 2 else pos[0] if mode in (3, 6) and pos else None
                page = pdf[index]
                try:
                    y = page.get_height()-y if y is not None else None
                finally:
                    page.close()
                locations = [dict(kind='pdf_destination', page_number=index+1, y=y)]
            else:
                issues.append(f'outline_destination_unresolved:{node_id}')
            nodes.append(dict(node_id=node_id, parent_id=parent, title=bookmark.get_title(),
                              order=ordinal, basis='source_directory', locations=locations))
    if not nodes:
        # An absent PDF bookmark tree does not prove absence of a printed contents page.
        issues.append('native_outline_absent_printed_contents_not_resolved')
    return dict(has_source_directory=True if nodes else None,
                status='partial' if issues else 'complete', nodes=nodes, issues=issues)


def _location(box, page_number, height):
    box = box.to_top_left_origin(height)
    return dict(kind='pdf_region', page_number=page_number,
                bbox=[float(box.l), float(box.t), float(box.r), float(box.b)])


def _assign_directory(locations, directory):
    """Use explicit bookmark destinations, including multiple sections per page."""
    if not directory['nodes']:
        return [], 'unresolved'
    boundaries = []
    for node in directory['nodes']:
        if not node['locations']:
            return [], 'unresolved'
        loc = node['locations'][0]
        boundaries.append(((loc['page_number'], loc.get('y') or 0.0), node['node_id']))
    if boundaries != sorted(boundaries, key=lambda pair: pair[0]):
        return [], 'unresolved'
    found = []
    for loc in locations:
        point = (loc['page_number'], loc['bbox'][1])
        eligible = [identity for boundary, identity in boundaries if boundary <= point]
        if eligible and eligible[-1] not in found:
            found.append(eligible[-1])
    return found, 'assigned' if found else 'outside_directory'


def _observations(result):
    """Retain actual OCR/source attribution and confidence, without inventing text."""
    from docling.utils.font_style import parse_font_style
    observed = []
    for page in result.pages:
        parsed = page.parsed_page
        cells = list(parsed.textline_cells) if parsed is not None else list(page.cells)
        if parsed is not None:
            cells += [cell for cell in page.cells if cell.from_ocr]
        seen = set()
        for cell in cells:
            location = _location(cell.rect.to_bounding_box(), page.page_no, page.size.height)
            identity = (cell.text, tuple(location['bbox']), cell.from_ocr)
            if identity in seen:
                continue
            seen.add(identity)
            font = getattr(cell, 'font_name', '')
            # Preserve the actual name; normalize only a compound style suffix for
            # Docling's existing font parser (e.g. BoldObl -> Bold-Obl).
            normalized = re.sub(r'(?i)(bold|demi|semi)(obl)$', r'\1-\2', font or '')
            style = parse_font_style(normalized)
            observed.append(dict(page_number=page.page_no, text=cell.text,
                from_ocr=cell.from_ocr, confidence=cell.confidence,
                font_name=font, font_weight=style.weight, font_italic=style.italic,
                location=location))
    return observed


def _origin(locations, observations):
    flags = set()
    for loc in locations:
        x0, y0, x1, y1 = loc['bbox']
        for cell in observations:
            if cell['page_number'] != loc['page_number']:
                continue
            a, b, c, d = cell['location']['bbox']
            if x0 <= (a+c)/2 <= x1 and y0 <= (b+d)/2 <= y1:
                flags.add(cell['from_ocr'])
    return 'mixed' if len(flags) > 1 else 'ocr' if flags == {True} else 'source' if flags == {False} else 'unknown'


def _checked_table(cells, row_count, column_count):
    table=dict(status='complete',processor_ref='table',row_count=row_count,column_count=column_count,cells=cells)
    try:
        TableContent.model_validate_json(json.dumps(table))
    except ValidationError as error:
        # Preserve an explicit failed table; never pick a conflicting span.
        errors=error.errors(include_input=False,include_url=False)
        if any(e['msg'] not in ('Value error, overlapping cells','Value error, cell outside table grid') for e in errors):
            raise
        issues=['invalid_parser_table_grid:'+e['msg'].removeprefix('Value error, ') for e in errors]
        table.update(status='failed',cells=[],issues=issues)
    return table


def _blocks(document, observations, directory, store):
    # Include furniture explicitly: headers/footers are preserved and can be filtered later.
    from docling_core.types.doc import ContentLayer, PictureItem, TableItem
    items, seen = [], set()
    for root in (document.body, document.furniture):
        for item, level in document.iterate_items(root=root, included_content_layers=set(ContentLayer)):
            if item.self_ref not in seen:
                items.append((item, level)); seen.add(item.self_ref)
    ids = {item.self_ref: item.self_ref.removeprefix('#/').replace('/', '-') for item, _ in items}
    blocks = []
    for item, _ in items:
        locations = [_location(p.bbox, p.page_no, document.pages[p.page_no].size.height) for p in item.prov]
        if not locations:
            raise ValueError(f'parser item lacks source location: {item.self_ref}')
        kind = 'table' if isinstance(item, TableItem) else 'image' if isinstance(item, PictureItem) else 'text'
        block_id = ids[item.self_ref]
        assigned, assignment = _assign_directory(locations, directory)
        origin = _origin(locations, observations)
        role = {'section_header': 'heading', 'title': 'heading', 'caption': 'caption',
                'footnote': 'footnote', 'page_header': 'header', 'page_footer': 'footer'}.get(item.label.value, 'body')
        block = dict(block_id=block_id, order=len(blocks), type=kind, role=role, processor_ref='layout',
            text_origin=origin, locations=locations, directory_node_ids=assigned, directory_assignment=assignment,
            ocr=dict(status='not_applicable'), description=dict(status='not_applicable' if kind == 'text' else 'not_processed'),
            tagging=dict(status='not_processed', issues=['fixed_business_taxonomy_not_configured']),
            status='complete', related_blocks=[], resources=[], links=[])
        if kind == 'text':
            block['text'] = item.text
        elif kind == 'table':
            cells = []
            for cell in item.data.table_cells:
                cell_locations = []
                if cell.bbox is not None and len(item.prov) == 1:
                    page_no = item.prov[0].page_no
                    cell_locations = [_location(cell.bbox, page_no, document.pages[page_no].size.height)]
                cells.append(dict(row=cell.start_row_offset_idx, column=cell.start_col_offset_idx,
                    row_span=cell.row_span, column_span=cell.col_span, text=cell.text,
                    is_header=cell.column_header or cell.row_header, locations=cell_locations))
            block['table'] = _checked_table(cells,item.data.num_rows,item.data.num_cols)
            if block['table']['status']=='failed':
                block.update(status='partial',issues=block['table']['issues'])
        if kind in ('table', 'image'):
            crop = item.get_image(document)
            if crop is not None:
                buf = BytesIO(); crop.save(buf, format='PNG')
                block['resources'] = [dict(resource_id=f'{block_id}-crop', role='source_crop',
                    mime_type='image/png', object_ref=store.content.put_object(buf.getvalue()).model_dump(mode='json'))]
            elif kind == 'image':
                raise ValueError(f'picture crop unavailable: {item.self_ref}')
            if kind=='table' and block['table']['status']=='failed' and not block['resources']:
                raise ValueError(f'invalid table grid and source crop unavailable: {item.self_ref}')
            for field, relation in (('captions', 'caption'), ('footnotes', 'footnote')):
                for ref in getattr(item, field, []):
                    if ref.cref in ids:
                        block['related_blocks'].append(dict(block_id=ids[ref.cref], relation=relation))
        if origin in ('ocr', 'mixed'):
            text = item.text if kind == 'text' else '\n'.join(c['text'] for c in block.get('table', {}).get('cells', []))
            if origin == 'mixed' or kind == 'image':
                # Do not relabel native words as OCR; retain the raw OCR observations separately.
                block['ocr'] = dict(status='partial', processor_ref='ocr', issues=['mixed_or_image_text_requires_cell_review'])
            else:
                block['ocr'] = dict(status='complete', text=text, processor_ref='ocr')
        elif origin == 'unknown':
            block['ocr'] = dict(status='not_processed', issues=['no_overlapping_text_observations'])
        if getattr(item, 'hyperlink', None):
            block['links'] = [dict(text=getattr(item, 'text', ''), target_url=str(item.hyperlink), locations=locations)]
        blocks.append(block)
    return blocks


def ingest_pdf(store, *, source_path, material, source_version_id, parse_id, model_root,
               language, ocr_mode='auto', source_url=None, max_pages=100, timeout=300, make_default=True,
               page_range=None):
    """Import a local PDF; the acquisition event is this explicit local import.

    Repeating the same ID/input/recipe reuses its frozen package before inference.
    Changing any of these requires a new explicit parse ID.
    """
    material = Material.model_validate(material)
    model_root = Path(model_root)
    if not model_root.is_absolute() or not model_root.is_dir():
        raise ValueError('model_root must be an existing absolute directory')
    if ocr_mode not in ('auto', 'full_page') or language != 'en':
        raise ValueError('this provider currently supports en with auto/full_page OCR only')
    if page_range is not None and (len(page_range)!=2 or any(type(v) is not int for v in page_range)
                                   or not 1 <= page_range[0] <= page_range[1]):
        raise ValueError('page_range requires two ordered positive physical page numbers')
    source_bytes = Path(source_path).read_bytes()
    if not source_bytes.startswith(b'%PDF-'):
        raise ValueError('input is not a PDF')
    weights = _model_files(model_root)
    recipe = dict(adapter=ADAPTER_VERSION, versions={n: version(n) for n in
        ('docling-slim', 'docling-core', 'docling-ibm-models', 'docling-parse', 'rapidocr', 'onnxruntime', 'pypdfium2')},
        weights=weights, language=language, ocr_mode=ocr_mode, max_pages=max_pages, timeout=timeout,
        device='cpu', threads=4, images_scale=1.5, table_mode='accurate',
        sections=SECTION_VERSION, page_range=list(page_range) if page_range is not None else None)
    config_hash = digest(canonical(recipe))
    try:
        old = store.export_package(parse_id)
    except DocumentStoreError as error:
        if error.code != 'NOT_FOUND':
            raise
    else:
        if (old.material != material or old.source.source_version_id != source_version_id or
            old.source.source_url != source_url or old.parse.config_hash != config_hash or
            store.read_source(parse_id) != source_bytes):
            raise DocumentStoreError('IDENTITY_CONFLICT', 'parse ID already binds another input/recipe')
        return dict(publication=store.publish(old, make_default=make_default), local_inference_ran=False, remote_model_calls=0)

    source = None
    try:
        existing = store.get_source_version(source_version_id)
    except DocumentStoreError as error:
        if error.code != 'NOT_FOUND':
            raise
    else:
        if (existing.material_id != material.material_id or existing.format != 'pdf' or
            existing.source_url != source_url or store.content.read_object(existing.object_ref) != source_bytes):
            raise DocumentStoreError('IDENTITY_CONFLICT', 'source version already binds another original')
        source = existing.model_dump(mode='json')

    # Offline settings avoid invisible download/service fallbacks during conversion.
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    from docling.datamodel.base_models import InputFormat, DocumentStream
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions, HeadingHierarchyOptions
    from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice
    from docling.document_converter import DocumentConverter, PdfFormatOption
    stamp = datetime.now(timezone.utc)
    options = PdfPipelineOptions(artifacts_path=model_root, do_ocr=True,
        ocr_options=RapidOcrOptions(lang=[language], force_full_page_ocr=ocr_mode == 'full_page'),
        generate_page_images=True, generate_picture_images=True, generate_parsed_pages=True,
        images_scale=1.5, heading_hierarchy_options=HeadingHierarchyOptions(enabled=True),
        accelerator_options=AcceleratorOptions(num_threads=4, device=AcceleratorDevice.CPU), document_timeout=timeout)
    converter = DocumentConverter(allowed_formats=[InputFormat.PDF],
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
    kwargs = dict(page_range=tuple(page_range)) if page_range is not None else {}
    result = converter.convert(DocumentStream(name='source.pdf', stream=BytesIO(source_bytes)), max_num_pages=max_pages, **kwargs)
    if result.status.value != 'success':
        raise ValueError(f'conversion did not finish: {result.status}; {result.errors}')
    completed = datetime.now(timezone.utc)
    observations = _observations(result)
    native_directory = _native_directory(source_bytes)
    blocks = _blocks(result.document, observations, native_directory, store)
    directory, blocks = build_sections(blocks, observations, native_directory)
    attach_text_lines(blocks, observations)
    passages = build_passages(blocks, observations, directory)
    if page_range is not None:
        directory['issues'].append(f'partial_page_coverage:{page_range[0]}-{page_range[1]}')
    raw_output = dict(recipe=recipe, started_at=stamp.isoformat(), completed_at=completed.isoformat(),
        document=result.document.export_to_dict(), text_observations=observations,
        native_directory=native_directory, section_issues=directory['issues'],
        processed_pages=[page.page_no for page in result.pages])
    output_ref = store.content.put_object(canonical(raw_output))
    processors = [dict(processor_id='adapter', step='normalization', tool_name='uteki-docling', tool_version=ADAPTER_VERSION)]
    for identity, tool, model in (('layout', 'docling-ibm-models', 'docling-layout-heron'),
        ('table', 'docling-ibm-models', 'TableFormer-accurate'), ('ocr', 'rapidocr', 'PP-OCRv6-small-det-rec+mobile-v2-cls')):
        processors.append(dict(processor_id=identity, step=identity, tool_name=tool, tool_version=version(tool),
            model=dict(provider='local', model_id=model, model_version='sha256:'+weights[identity])))
    processors.append(dict(processor_id='bookmarks', step='source_directory', tool_name='pypdfium2', tool_version=version('pypdfium2')))
    processors.append(dict(processor_id='sections', step='section_structure', tool_name='uteki-pdf-sections', tool_version=SECTION_VERSION))
    package = DocumentPackage.model_validate_json(json.dumps(dict(
        material=material.model_dump(mode='json'),
        source=source or dict(source_version_id=source_version_id, material_id=material.material_id, format='pdf',
            object_ref=store.content.put_object(source_bytes).model_dump(mode='json'), source_url=source_url,
            acquisition_method='manual_upload', acquired_at=stamp.isoformat(), ingested_at=completed.isoformat()),
        parse=dict(parse_id=parse_id, schema_version='document-v3', material_id=material.material_id, source_version_id=source_version_id,
            config_hash=config_hash, parser_output_ref=output_ref.model_dump(mode='json'), processors=processors,
            started_at=stamp.isoformat(), completed_at=completed.isoformat(), status='partial', directory_schema=directory,
            passages=passages,
            issues=['business_tagging_not_configured', 'image_table_descriptions_not_generated',
                    'printed_contents_and_all_pdf_link_annotations_not_verified',
                    'typographic_passage_grouping_requires_source_review']+
                    ['table_structure_failed:'+b['block_id'] for b in blocks if b.get('table',{}).get('status')=='failed']),
        blocks=blocks)))
    return dict(publication=store.publish(package, make_default=make_default), local_inference_ran=True, remote_model_calls=0,
        pages=len(result.pages), blocks=len(package.blocks), seconds=(completed-stamp).total_seconds(),
        ocr_observations=sum(c['from_ocr'] for c in observations), status=package.parse.status)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('data-root', 'source', 'material', 'model-root'):
        parser.add_argument('--'+name, type=Path, required=True)
    for name in ('source-version-id', 'parse-id', 'language'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--source-url')
    parser.add_argument('--ocr-mode', choices=('auto', 'full_page'), default='auto')
    parser.add_argument('--max-pages', type=int, default=100)
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--no-default', action='store_true')
    parser.add_argument('--page-start', type=int)
    parser.add_argument('--page-end', type=int)
    args = parser.parse_args()
    if (args.page_start is None) != (args.page_end is None):
        parser.error('--page-start and --page-end must be supplied together')
    material = Material.model_validate_json(args.material.read_bytes())
    # Initialization is explicit via the existing documents init command.
    with DocumentStore.open(args.data_root) as store:
        result = ingest_pdf(store, source_path=args.source, material=material, model_root=args.model_root,
            source_version_id=args.source_version_id, parse_id=args.parse_id, source_url=args.source_url,
            language=args.language, ocr_mode=args.ocr_mode, max_pages=args.max_pages, timeout=args.timeout,
            make_default=not args.no_default,
            page_range=(args.page_start,args.page_end) if args.page_start is not None else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
