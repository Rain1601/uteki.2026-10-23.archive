from __future__ import annotations
from apps.review_workbench.assets import asset_text

import argparse
import gzip
import html
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from apps.review_workbench.pages.company_data import render_company_data, render_document_status
from apps.review_workbench.pages.research_archive_ui import render_archive
from apps.review_workbench.components.visual_system import workbench_page, theme_html
from apps.review_workbench.data.research_archive_import import import_rows
from uteki.agents.research_archive import Store, ArchiveError, ConflictError
from apps.review_workbench.data.document_library import index_url, resolve_index
from uteki.agents.material_library import load_catalog
from apps.review_workbench.pages.earnings_reader import render_transcript
from apps.review_workbench.pages.cloud_spike import render_cloud_spike
from apps.review_workbench.pages.cloud_analysis import render_cloud_analysis
from apps.review_workbench.pages.document_index import (
    load_jsonl,
    render_document_index_page,
    render_index_source_document,
)


ROOT = Path(__file__).resolve().parents[2]
RESEARCH_DATA_DIR = ROOT / "data/research_data/alphabet_2025_10k/v0.2-candidate"
DEFAULT_DATA = RESEARCH_DATA_DIR / "business_map.json"
EVIDENCE_BUNDLE_DATA = RESEARCH_DATA_DIR / "evidence_bundle.json"
RESEARCH_DATA_MANIFEST = RESEARCH_DATA_DIR / "manifest.json"
SOURCE_EXCERPT = ROOT / "data/source_documents/alphabet_2025_10k/review_excerpt.json"
RAW_SOURCE_GZIP = ROOT / "data/source_documents/alphabet_2025_10k/source.html.gz"
SOURCE_MANIFEST = RAW_SOURCE_GZIP.parent / "manifest.json"
SOURCE_ASSETS = RAW_SOURCE_GZIP.parent / "assets"
DOCUMENT_INDEX_DIR = RAW_SOURCE_GZIP.parent / "indexes/v0.1"
DOCUMENT_INDEX_MANIFEST = DOCUMENT_INDEX_DIR / "manifest.json"
DOCUMENT_INDEX_DATA = DOCUMENT_INDEX_DIR / "index.json"
DOCUMENT_BLOCKS_DATA = DOCUMENT_INDEX_DIR / "blocks.jsonl"
DOCUMENT_ASSETS_DATA = DOCUMENT_INDEX_DIR / "assets.json"
COMPANY_UNIVERSE_DATA = ROOT / "data/company_universe/v0.1-candidate/companies.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def evidence_bundle_views(bundle: dict) -> tuple[dict, dict]:
    """Expose the published bundle through the legacy read-only UI view shape."""
    source_snapshot_ids = bundle.get("source_snapshot_ids", [])
    source_snapshot_id = source_snapshot_ids[0] if source_snapshot_ids else None
    claims = {
        "schema_version": bundle["schema_version"],
        "source_snapshot_id": source_snapshot_id,
        "claims": bundle["claims"],
    }
    spans = {
        "schema_version": bundle["schema_version"],
        "source_snapshot_id": source_snapshot_id,
        "spans": [
            {
                "claim_id": item["claim_id"],
                "evidence_id": item["evidence_id"],
                "quote_en": item["quote_en"],
                "quote_zh": item["quote_zh"],
            }
            for item in bundle["evidence_links"]
        ],
    }
    return claims, spans


def document_index_status_label(manifest: dict) -> str:
    version = manifest["index_version"]
    return f"Index {version} · Frozen" if manifest["status"] == "frozen" else f"Index Candidate {version.removesuffix('-candidate')}"


def esc(value: object) -> str:
    return html.escape(str(value))


def bilingual(en: object, zh: object) -> str:
    return f"<span data-lang='en'>{esc(en)}</span><span data-lang='zh'>{esc(zh)}</span>"


def render_original_source_document(raw_html: str, excerpt: dict) -> str:
    """Add a read-only evidence bridge to the immutable SEC filing HTML."""
    evidence_blocks = [
        {
            "ordinal": item["ordinal"],
            "text": item["text"],
            "translation_zh": item["translation_zh"],
        }
        for item in excerpt["paragraphs"]
    ]
    payload = json.dumps(evidence_blocks, ensure_ascii=False).replace("</", "<\\/")
    bridge = f"""<style id="uteki-source-style">{asset_text('source_bridge.css')}</style><script id="uteki-source-bridge">{asset_text('source_bridge.js').replace('__UTEKI_DATA_JSON__', payload)}</script>"""
    marker = "</head>"
    if marker not in raw_html.lower():
        raise ValueError("SEC source HTML has no closing head element")
    position = raw_html.lower().index(marker)
    return raw_html[:position] + bridge + raw_html[position:]


def parent_and_children(data: dict) -> tuple[dict[str, str], dict[str, list[str]]]:
    if data.get("schema_version") == "business-map-v0.2":
        raise ValueError("business_map_v2_display_requires_basis_aware_renderer")
    hierarchy_kinds = {"reported_under", "part_of", "revenue_component_of"}
    parents: dict[str, str] = {}
    for relationship in data["relationships"]:
        if relationship["kind"] not in hierarchy_kinds:
            continue
        source_id = relationship["source_id"]
        if source_id in parents:
            raise ValueError(f"business has multiple hierarchy parents: {source_id}")
        parents[source_id] = relationship["target_id"]
    children: dict[str, list[str]] = {}
    for item in data["businesses"]:
        children.setdefault(parents.get(item["id"], "__root__"), []).append(item["id"])
    return parents, children


def validate_claims(data: dict, claims_data: dict, excerpt: dict, spans_data: dict | None = None) -> None:
    if spans_data is None:
        _, spans_data = evidence_bundle_views(load_json(EVIDENCE_BUNDLE_DATA))
    business_ids = {item["id"] for item in data["businesses"]}
    evidence = {item["id"]: item for item in data["evidence"]}
    paragraphs = {item["ordinal"]: item for item in excerpt["paragraphs"]}
    claim_ids: set[str] = set()
    expected_links: set[tuple[str, str]] = set()
    for claim in claims_data["claims"]:
        if claim["id"] in claim_ids:
            raise ValueError(f"duplicate claim id: {claim['id']}")
        claim_ids.add(claim["id"])
        if claim["business_id"] not in business_ids:
            raise ValueError(f"unknown business in claim: {claim['id']}")
        if not claim.get("evidence_ids"):
            raise ValueError(f"claim has no evidence: {claim['id']}")
        for evidence_id in claim["evidence_ids"]:
            expected_links.add((claim["id"], evidence_id))
            if evidence_id not in evidence:
                raise ValueError(f"unknown evidence {evidence_id} in claim {claim['id']}")
            reference = evidence[evidence_id]
            paragraph = paragraphs.get(reference["paragraph_ordinal"])
            if not paragraph or paragraph["text_hash"] != reference["text_hash"]:
                raise ValueError(f"evidence does not resolve to source: {evidence_id}")
    actual_links: set[tuple[str, str]] = set()
    for span in spans_data["spans"]:
        key = (span["claim_id"], span["evidence_id"])
        if key in actual_links:
            raise ValueError(f"duplicate evidence span: {key[0]} / {key[1]}")
        actual_links.add(key)
        if key not in expected_links:
            raise ValueError(f"orphan evidence span: {key[0]} / {key[1]}")
        reference = evidence[key[1]]
        paragraph = paragraphs[reference["paragraph_ordinal"]]
        if span["quote_en"] not in paragraph["text"]:
            raise ValueError(f"English quote does not match source: {key[0]} / {key[1]}")
        if span["quote_zh"] not in paragraph["translation_zh"]:
            raise ValueError(f"Chinese quote does not match translation: {key[0]} / {key[1]}")
    missing_links = expected_links - actual_links
    if missing_links:
        claim_id, evidence_id = sorted(missing_links)[0]
        raise ValueError(f"claim evidence has no exact span: {claim_id} / {evidence_id}")


def span_index(spans_data: dict) -> dict[tuple[str, str], dict]:
    return {(item["claim_id"], item["evidence_id"]): item for item in spans_data["spans"]}


def evidence_context(data: dict, excerpt: dict) -> tuple[dict[str, dict], dict[int, dict]]:
    evidence = {item["id"]: item for item in data["evidence"]}
    paragraphs = {item["ordinal"]: item for item in excerpt["paragraphs"]}
    return evidence, paragraphs


def claim_ordinals(claim: dict, evidence: dict[str, dict]) -> list[int]:
    return list(dict.fromkeys(evidence[value]["paragraph_ordinal"] for value in claim["evidence_ids"]))


def preview(value: str, length: int = 92) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= length else normalized[: length - 1].rstrip() + "…"


def render_tree(data: dict, selected: str) -> str:
    businesses = {item["id"]: item for item in data["businesses"]}
    _, children = parent_and_children(data)

    def branch(item_id: str) -> str:
        item = businesses[item_id]
        nested = children.get(item_id, [])
        revenue = next((value for value in item.get("importance_signals", []) if "2025 revenue:" in value), "")
        child_html = "" if not nested else f"<ul>{''.join(branch(value) for value in nested)}</ul>"
        toggle = "<button class='toggle' type='button' aria-label='Toggle'>⌄</button>" if nested else "<span class='toggle-space'></span>"
        return f"""<li data-branch='{esc(item_id)}'>{toggle}<button type='button' class='tree-node {'active' if item_id == selected else ''}' data-select='{esc(item_id)}'>
          <span class='node-main'><strong>{esc(item['name'])}</strong><small>{esc(item['kind'])}</small></span><span class='node-metric'>{esc(revenue.replace('2025 revenue: ', ''))}</span>
        </button>{child_html}</li>"""

    return f"<ul class='tree'>{''.join(branch(value) for value in children.get('__root__', []))}</ul>"


def render_evidence_cards(claim: dict, evidence: dict[str, dict], paragraphs: dict[int, dict], spans: dict[tuple[str, str], dict]) -> str:
    cards = []
    total = len(claim["evidence_ids"])
    for index, evidence_id in enumerate(claim["evidence_ids"], start=1):
        reference = evidence[evidence_id]
        paragraph = paragraphs[reference["paragraph_ordinal"]]
        anchor = spans[(claim["id"], evidence_id)]
        cards.append(f"""<button type='button' class='evidence-card' data-evidence='{esc(evidence_id)}' data-ordinal='{reference['paragraph_ordinal']}'>
          <span class='evidence-index'>{index}/{total}</span><span class='evidence-location'>¶{reference['paragraph_ordinal']} · {bilingual('source','原文')}</span>
          <span class='evidence-snippet' data-quote-en='{esc(anchor['quote_en'])}' data-quote-zh='{esc(anchor['quote_zh'])}'>{bilingual(preview(anchor['quote_en']), preview(anchor['quote_zh']))}</span>
        </button>""")
    return "".join(cards)


def render_knowledge_details(data: dict, claims_data: dict, excerpt: dict, spans_data: dict, selected: str) -> str:
    evidence, paragraphs = evidence_context(data, excerpt)
    spans = span_index(spans_data)
    claims_by_business: dict[str, list[dict]] = {}
    for claim in claims_data["claims"]:
        claims_by_business.setdefault(claim["business_id"], []).append(claim)
    rendered = []
    for item in data["businesses"]:
        claim_rows = []
        for index, claim in enumerate(claims_by_business.get(item["id"], [])):
            ordinals = ",".join(str(value) for value in claim_ordinals(claim, evidence))
            claim_rows.append(f"""<article class='claim {'active' if index == 0 else ''}' data-claim='{esc(claim['id'])}' data-ordinals='{ordinals}'>
              <button type='button' class='claim-main'>
                <span><span class='claim-label'>{bilingual(claim['label_en'], claim['label_zh'])}</span><strong>{bilingual(claim['value_en'], claim['value_zh'])}</strong></span>
                <span class='claim-meta'><i>{bilingual('explicit','明确披露') if claim['basis'] == 'explicit' else bilingual('derived','计算所得')}</i><b>{len(claim['evidence_ids'])} {bilingual('sources','条证据')}</b></span>
              </button>
              <div class='evidence-cards'>{render_evidence_cards(claim, evidence, paragraphs, spans)}</div>
            </article>""")
        rendered.append(f"""<section class='knowledge-detail {'active' if item['id'] == selected else ''}' data-detail='{esc(item['id'])}'>
          <div class='detail-heading'><div class='detail-kicker'>{esc(item['kind'])}</div><h2>{esc(item['name'])}</h2><p>{bilingual('Every statement below is independently traceable.','下方每一条知识均可独立追溯。')}</p></div>
          <div class='claim-list'>{''.join(claim_rows)}</div>
        </section>""")
    return "".join(rendered)


def render_source(excerpt: dict) -> str:
    return "".join(
        f"""<article class='source-row' data-paragraph='{item['ordinal']}'>
          <div class='source-marker'><b>¶{item['ordinal']}</b><span></span></div>
          <div><div class='source-path'>{esc(' › '.join(item['section_path']))}</div>
          <p class='source-translation' lang='zh-CN'>{esc(item['translation_zh'])}</p>
          <div class='original-label'>{bilingual('SEC original','SEC 英文原文')}</div><p class='source-original' lang='en'>{esc(item['text'])}</p>
          <div class='source-hash'>SHA · {esc(item['text_hash'][:12])}</div></div>
        </article>"""
        for item in excerpt["paragraphs"]
    )


def research_data_status_label(manifest: dict) -> str:
    version = manifest["release_version"].removesuffix("-candidate")
    return f"Data {version} · Frozen" if manifest["status"] == "frozen" else f"Data candidate {version}"


def page_shell(body: str, data: dict, bundle: dict, release_manifest: dict) -> str:
    counts = release_manifest["counts"]
    metadata = f"""Alphabet · FY2025 10-K · Business Map {esc(bundle['business_map_version'])} · {counts['claims']} {bilingual('claims','条 Claims')} · {counts['metrics']} {bilingual('metrics','项 Metrics')} · {counts['evidence_links']} {bilingual('evidence','条 Evidence')}"""
    return f"""<!doctype html><html lang='zh'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Uteki · Alphabet Data Agent Result</title>
<style>{asset_text('result.css')}</style></head><body>
<header><div class='brand'><i>Uteki</i> / Data</div><div class='page-name'>{bilingual('Data Agent result','Data Agent 解析结果')}</div><span class='status'>{esc(research_data_status_label(release_manifest))}</span><div class='meta'>{metadata}</div><div class='lang'><button id='en'>EN</button><button id='zh'>中文</button></div></header>{body}
<script>{asset_text('result.js')}</script></body></html>"""


@workbench_page('result')
def render_result_page(
    data: dict,
    excerpt: dict,
    selected: str | None = None,
    claims_data: dict | None = None,
    spans_data: dict | None = None,
    bundle: dict | None = None,
    release_manifest: dict | None = None,
) -> str:
    bundle = bundle or load_json(EVIDENCE_BUNDLE_DATA)
    release_manifest = release_manifest or load_json(RESEARCH_DATA_MANIFEST)
    bundle_claims, bundle_spans = evidence_bundle_views(bundle)
    claims_data = claims_data or bundle_claims
    spans_data = spans_data or bundle_spans
    validate_claims(data, claims_data, excerpt, spans_data)
    selected = selected if any(item["id"] == selected for item in data["businesses"]) else data["businesses"][0]["id"]
    body = f"""<main class='split'><section class='knowledge-pane'>
      <div class='pane-head'><h1>{bilingual('Structured research data','结构化研究数据')}</h1><p>{bilingual('Business Map is one view of the published Data Snapshot.','Business Map 是已发布 Data Snapshot 的一个视图。')} · {esc(bundle['data_snapshot_id'])} · {esc(bundle['bundle_id'])}</p></div>
      <div class='tree-wrap'>{render_tree(data, selected)}</div>{render_knowledge_details(data, claims_data, excerpt, spans_data, selected)}
    </section><section class='source-pane'>
      <div class='pane-head source-head'><div><h1>{bilingual('Evidence source','证据原文')}</h1><p>{bilingual('Same evidence, two reading modes.','同一条证据，两种阅读方式。')}</p></div><div class='source-actions'><div class='view-switch'><button type='button' data-view='original'>{bilingual('Original layout','原始版式')}</button><button type='button' data-view='structured'>{bilingual('Structured','结构化')}</button></div><a href='{esc(data['evidence'][0]['source_url'])}' target='_blank'>SEC ↗</a></div></div>
      <iframe class='original-frame' title='{esc('SEC original filing layout')}' src='/source/original' sandbox='allow-scripts allow-same-origin allow-popups'></iframe>
      <div class='structured-view'><div class='source-notice' data-lang='zh'>{esc(excerpt['translation']['notice_zh'])}</div><div class='source-document'>{render_source(excerpt)}</div></div>
    </section></main>"""
    return page_shell(body, data, bundle, release_manifest)


def render_page(data: dict, reviews: dict) -> str:
    return render_result_page(data, load_json(SOURCE_EXCERPT))


def make_handler(data_path: Path, archive_path: Path | None = None, *, observation_root=None, observation_output_roots=(), score_path=None):
    observation_options = {'observation_root': observation_root, 'output_roots': tuple(observation_output_roots)}
    score_store = Path(score_path) if score_path is not None else ROOT / 'data/review_workbench/agent-result-scores-v1.json'
    archive = Store(archive_path or ROOT / 'data/research_archive/state.json')
    imports = import_rows(ROOT)
    archive.migrate_researchers({row['id']: {key: row[key] for key in ('researcher_id', 'researcher_label', 'config_version')} for row in imports}, dry_run=False)
    archive.seed(imports)
    class Handler(BaseHTTPRequestHandler):
        def archive_json(self, body, status=200):
            payload = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            if urlparse(self.path).path.startswith('/api/agent-results/'):
                self.agent_result_route(urlparse(self.path), write=True)
                return
            path = urlparse(self.path).path
            if path not in {'/api/research-archive', '/api/research-annotations', '/api/data-workspace/state'}:
                self.send_error(404); return
            host = self.headers.get('Host', '')
            origin = self.headers.get('Origin')
            if (urlparse('http://' + host).hostname not in {'localhost', '127.0.0.1', '::1'}
                    or (origin is not None and origin != 'http://' + host)
                    or self.headers.get('Sec-Fetch-Site') == 'cross-site'
                    or self.headers.get('X-Uteki-Request') != '1'
                    or self.headers.get('Content-Type', '').split(';')[0] != 'application/json'):
                self.archive_json({'error': 'Same-origin JSON requests only'}, 403); return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 100000:
                    raise ArchiveError('Invalid request size')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ArchiveError('Expected a JSON object')
                if path == '/api/data-workspace/state':
                    from apps.review_workbench.data.workspace_state import update_state, WorkspaceConflictError
                    try:
                        self.archive_json(update_state(ROOT, data))
                    except WorkspaceConflictError as error:
                        self.archive_json({'error': str(error)}, 409)
                    except OSError:
                        self.archive_json({'error': 'Workspace display state could not be saved'}, 503)
                    return
                snapshot_id = data.pop('snapshot_id')
                action = data.pop('action')
                revision = data.pop('expected_revision')
                if action == 'agent_edit':
                    raise ArchiveError('Agent revisions must come from a recorded local run')
                for protected in ('agent_provenance', 'editor_type', 'citation_errors'):
                    data.pop(protected, None)
                data.pop('actor', None)
                operation = archive.annotate if path == '/api/research-annotations' else archive.act
                self.archive_json(operation(snapshot_id, action, revision, **data))
            except ConflictError as error:
                self.archive_json({'error': str(error)}, 409)
            except (ArchiveError, KeyError, TypeError, ValueError) as error:
                self.archive_json({'error': str(error)}, 400)

        def workspace_route(self, parsed):
            """Canonical product pages; legacy research URLs remain readable."""
            from apps.review_workbench.components.site_navigation import (
                render_company_overview, render_materials, render_structured,
                render_reports, company_tabs, crumb)
            from urllib.parse import unquote
            path = parsed.path
            query = parse_qs(parsed.query)
            def send(page, content_type='text/html; charset=utf-8'):
                body = page.encode() if isinstance(page, str) else page
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
            if path == '/data-workspace' and not parsed.query:
                self.send_response(303)
                self.send_header('Location', '/agent-results')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return True
            if path in {'/data-workspace', '/data-workspace/source', '/data-workspace/source-meta'}:
                from apps.review_workbench.pages.data_workspace import render_data_workspace
                from apps.review_workbench.pages.source_preview import load_source_preview, PREVIEW_CSP
                selection = parse_qs(parsed.query, keep_blank_values=True)
                try:
                    if path == '/data-workspace':
                        send(render_data_workspace(ROOT, selection))
                    else:
                        result = load_source_preview(ROOT, selection)
                        if path.endswith('/source-meta'):
                            self.archive_json({k: v for k, v in result.items() if k not in {'content', 'headers'}})
                        else:
                            self.send_response(200)
                            self.send_header('Content-Type', result['mime_type'] + ('; charset=utf-8' if result['mime_type'].startswith('text/') else ''))
                            self.send_header('Content-Length', str(len(result['content'])))
                            for name, value in result['headers'].items():
                                self.send_header(name, value)
                            self.end_headers()
                            self.wfile.write(result['content'])
                except (KeyError, TypeError, ValueError, OSError) as error:
                    status = 503 if isinstance(error, OSError) else 400
                    if path.endswith('/source-meta'):
                        self.archive_json({'error': str(error)}, status)
                    else:
                        from apps.review_workbench.pages.data_workspace import shell, empty
                        from apps.review_workbench.components.site_navigation import bi, e
                        content = empty('当前产物无法读取，请返回运行结果重新选择。', 'This artifact is unavailable. Choose again from Results.')
                        content += '<details><summary>' + bi('问题详情', 'Details') + '</summary><p>' + e(error) + '</p></details><a href="/agent-results">' + bi('返回运行结果', 'Back to results') + '</a>'
                        payload = shell(content, '', {'selection': {}, 'revision': 0}).encode() if path == '/data-workspace' else ('<!doctype html><meta charset="utf-8">' + content).encode()
                        self.send_response(status)
                        self.send_header('Content-Type', 'text/html; charset=utf-8')
                        self.send_header('Content-Length', str(len(payload)))
                        self.send_header('Cache-Control', 'no-store')
                        if path != '/data-workspace':
                            self.send_header('Content-Security-Policy', PREVIEW_CSP)
                            self.send_header('X-Content-Type-Options', 'nosniff')
                        self.end_headers()
                        self.wfile.write(payload)
                return True
            if path == '/extractions':
                from apps.review_workbench.pages.direct_extractions import render_direct_extractions
                from apps.review_workbench.components.site_navigation import bi, page
                try:
                    send(render_direct_extractions(ROOT, parse_qs(parsed.query, keep_blank_values=True)))
                except (KeyError, ValueError, OSError) as error:
                    send(page('抽取产物不可用', '<h1>' + bi('抽取产物不可用', 'Extraction artifacts unavailable')
                              + '</h1><p>' + html.escape(str(error)) + '</p><a href="/extractions">'
                              + bi('返回运行目录', 'Return to runs') + '</a>'))
                return True
            if path in {'/evaluation', '/evaluation/source'}:
                from apps.review_workbench.pages.data_evaluation import render_evaluation
                from apps.review_workbench.data.evaluation_artifacts import load_raw_source
                selection = parse_qs(parsed.query, keep_blank_values=True)
                try:
                    if path == '/evaluation':
                        send(render_evaluation(ROOT, selection))
                    else:
                        if set(selection) != {'dataset', 'source'} or any(len(v) != 1 or not v[0].strip() for v in selection.values()):
                            raise ValueError('Explicit dataset and source required')
                        raw = load_raw_source(ROOT, selection['dataset'][0], selection['source'][0])
                        mime = raw['mime_type']
                        safe_type = mime if mime in {'text/html', 'application/pdf', 'text/plain'} else 'application/octet-stream'
                        self.send_response(200)
                        self.send_header('Content-Type', safe_type + ('; charset=utf-8' if safe_type.startswith('text/') else ''))
                        self.send_header('Content-Length', str(len(raw['content'])))
                        self.send_header('Content-Security-Policy', "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; form-action 'none'; base-uri 'none'")
                        self.send_header('X-Content-Type-Options', 'nosniff')
                        self.send_header('Cache-Control', 'no-store')
                        self.end_headers()
                        self.wfile.write(raw['content'])
                except (KeyError, ValueError, OSError) as error:
                    from apps.review_workbench.components.site_navigation import bi, page
                    message = page('评估内容不可用', '<h1>' + bi('评估内容不可用', 'Evaluation content unavailable') + '</h1><p>' + html.escape(str(error)) + '</p><a href="/evaluation">' + bi('返回数据选择', 'Return to dataset selection') + '</a>')
                    body = message.encode()
                    self.send_response(400 if isinstance(error, (KeyError, ValueError)) else 503)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(body)
                return True
            if path in {'/', '/companies'}:
                self.send_response(303)
                self.send_header('Location', '/agent-results')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return True
            legacy_target = None
            if path in {'/result', '/benchmark'} and not query.get('view'):
                legacy_target = '/companies/alphabet/data/business-map' + ('?' + parsed.query if parsed.query else '')
            elif path == '/data':
                from urllib.parse import quote
                legacy_target = '/companies/' + quote(query.get('company', ['alphabet'])[0], safe='') + '/data'
            elif path.startswith('/companies/') and len(path.strip('/').split('/')) == 2 and query.get('tab') == ['data']:
                legacy_target = path + '/data'
            if legacy_target:
                self.send_response(303)
                self.send_header('Location', legacy_target)
                self.end_headers()
                return True
            parts = path.strip('/').split('/')
            if len(parts) < 2 or parts[0] != 'companies' or 'documents' in parts:
                return False
            companies = load_json(COMPANY_UNIVERSE_DATA)['companies']
            company = next((c for c in companies if c['id'] == parts[1]), None)
            if company is None:
                self.send_error(404, 'Unknown company'); return True
            section = '/'.join(parts[2:])
            # Preserve bookmarks with an explicit legacy selection.
            if not section and query:
                return False
            catalog = load_catalog(ROOT) if company['id'] == 'alphabet' else {'documents': []}
            rows = archive.list(company=company['id'])
            bundle = load_json(EVIDENCE_BUNDLE_DATA) if company['id'] == 'alphabet' else None
            if not section:
                send(render_archive(company, rows, documents={d['id']: d for d in catalog.get('documents', [])}, active_section='overview'))
            elif section == 'materials' or section.startswith('materials/pdf/'):
                library = ROOT / 'data/reading_library' / company['id']
                manifest = library / 'download_manifest.json'
                docs = load_json(manifest).get('documents', []) if manifest.exists() else []
                docs = [d for d in docs if d.get('status') == 'downloaded' and d.get('path')]
                if section == 'materials':
                    send(render_materials(company, catalog, docs))
                else:
                    identity = unquote(section.removeprefix('materials/pdf/'))
                    doc = next((d for d in docs if Path(d['path']).stem == identity), None)
                    target = (library / doc['path']).resolve() if doc else None
                    if target is None or not target.is_relative_to(library.resolve()) or not target.is_file():
                        self.send_error(404, 'Unknown PDF'); return True
                    send(target.read_bytes(), 'application/pdf')
            elif section == 'data':
                from apps.review_workbench.pages.query_runs import collections
                from apps.review_workbench.pages.acceptance_view import registrations
                send(render_structured(company, bundle,
                    query_views=bool(collections(ROOT / 'data/query_views', company['id'])),
                    acceptance_views=bool(registrations(ROOT / 'data/acceptance_views', company['id']))))
            elif section == 'data/acceptance':
                from apps.review_workbench.pages.acceptance_view import render_acceptance
                try:
                    if set(query) - {'collection'} or any(len(v) != 1 for v in query.values()):
                        raise KeyError('Ambiguous acceptance selection')
                    send(render_acceptance(ROOT, ROOT / 'data/acceptance_views', company,
                                           query.get('collection', [None])[0]))
                except KeyError:
                    self.send_error(404, 'Unknown saved acceptance selection')
                except (OSError, ValueError):
                    self.send_error(503, 'Acceptance artifacts unavailable or changed')
            elif section == 'data/queries':
                from apps.review_workbench.pages.query_runs import render_query_runs
                try:
                    keys = ('collection', 'run', 'case')
                    selection = {key: query[key][0] for key in keys} if query else None
                    send(render_query_runs(ROOT, ROOT / 'data/query_views', company, selection))
                except KeyError:
                    self.send_error(404, 'Unknown saved query selection')
                except (OSError, ValueError):
                    self.send_error(503, 'Saved query artifacts unavailable or changed')
            elif section == 'data/dataset':
                from apps.review_workbench.pages.dataset_view import render_dataset
                try:
                    send(render_dataset(ROOT, ROOT / 'data/query_views', company,
                                        query['collection'][0], query.get('record', [None])[0]))
                except KeyError:
                    self.send_error(404, 'Unknown company dataset or record')
                except (OSError, ValueError):
                    self.send_error(503, 'Dataset artifacts unavailable or changed')
            elif section == 'data/business-map' and company['id'] == 'alphabet':
                page = render_result_page(load_json(data_path), load_json(SOURCE_EXCERPT),
                    query.get('selected', [None])[0], bundle=bundle,
                    release_manifest=load_json(RESEARCH_DATA_MANIFEST))
                context = '<div class="company-context">' + crumb(company, ('业务图', 'Business map')) + company_tabs(company['id'], 'data') + '</div>'
                page = page.replace('</nav>', '</nav>' + context, 1)
                send(page)
            elif section == 'reports' or section.startswith('reports/'):
                identity = unquote(section.removeprefix('reports/')) if section != 'reports' else query.get('snapshot', [None])[0]
                if identity and not any(r['id'] == identity for r in rows):
                    self.send_error(404, 'Unknown company report'); return True
                send(render_archive(company, rows, identity,
                    documents={d['id']: d for d in catalog.get('documents', [])},
                    researcher_id=query.get('researcher', [None])[0], scope=query.get('scope', [None])[0],
                    material_id=query.get('material', [None])[0]))
            else:
                self.send_error(404, 'Unknown company section')
            return True

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == '/agent-results' or parsed.path == '/api/agent-results' or parsed.path.startswith('/api/agent-results/'):
                self.agent_result_route(parsed)
                return
            if parsed.path == '/agent-runs' or parsed.path == '/api/agent-runs' or parsed.path.startswith('/api/agent-runs/'):
                self.agent_run_route(parsed)
                return
            if self.workspace_route(parsed):
                return
            if parsed.path == '/api/research-annotations':
                try:
                    self.archive_json(archive.annotations(parse_qs(parsed.query).get('snapshot_id', [''])[0]))
                except ArchiveError as error:
                    self.archive_json({'error': str(error)}, 400)
                return
            if parsed.path == '/api/research-archive':
                query = parse_qs(parsed.query)
                self.archive_json({'snapshots': archive.list(company='alphabet', scope=query.get('scope', [None])[0], researcher_id=query.get('researcher', [None])[0])}); return
            if parsed.path == '/api/research-archive/context':
                query = parse_qs(parsed.query)
                try:
                    from uteki.agents.research_archive_context import build_context
                    documents={d['id']:d for d in load_catalog(ROOT)['documents']}
                    material_id=query.get('material',[None])[0]
                    if material_id and material_id not in documents:
                        raise ArchiveError('Unknown current material')
                    self.archive_json(build_context(archive, 'alphabet', query.get('scope', ['company-drivers'])[0],
                        query.get('cutoff', [''])[0], strict=query.get('mode', ['strict'])[0] != 'retrospective', researcher_id=query.get('researcher', [None])[0],
                        material=documents.get(material_id),document_metadata=documents if material_id else None,
                        rerun_from=query.get('rerun_from',[None])[0]))
                except (ArchiveError, ValueError) as error:
                    self.archive_json({'error': str(error)}, 400)
                return
            if parsed.path == '/experiments':
                from html import escape
                runs = sorted((ROOT/'experiments/analysis_comparison').glob('*/review.html'))
                body = ('<!doctype html><meta charset="utf-8"><h1>分析实验</h1><a href="/result">返回研究结果</a><ul>'+''.join('<li><a href="/experiments/'+escape(p.parent.name)+'/review.html">'+escape(p.parent.name)+'</a></li>' for p in runs)+'</ul>').encode()
                body = theme_html(body.decode(), 'experiment').encode()
                self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers(); self.wfile.write(body)
                return
            if parsed.path.startswith('/experiments/'):
                from urllib.parse import unquote
                base=(ROOT/'experiments/analysis_comparison').resolve()
                target=(base/unquote(parsed.path.removeprefix('/experiments/'))).resolve()
                if not target.is_relative_to(base) or not target.is_file() or target.suffix not in {'.html','.json','.md'}:
                    self.send_error(404); return
                body=target.read_bytes()
                if target.suffix == '.html':
                    body = theme_html(body.decode('utf-8'), 'experiment').encode('utf-8')
                self.send_response(200); self.send_header('Content-Type',(mimetypes.guess_type(str(target))[0] or 'text/plain')+'; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
                return
            if '/documents/' in parsed.path and parsed.path.startswith('/companies/'):
                catalog = load_catalog(ROOT)
                resolved = resolve_index(parsed.path, catalog, ROOT)
                if resolved is None:
                    self.send_error(404, 'Unknown document or index version')
                    return
                doc, source, index_dir, suffix, base = resolved
                try:
                    manifest = load_json(index_dir / 'manifest.json')
                    index = load_json(index_dir / 'index.json')
                    blocks = load_jsonl(index_dir / 'blocks.jsonl')
                    assets = load_json(index_dir / 'assets.json')
                    content_type = 'text/html; charset=utf-8'
                    if suffix == '':
                        body = (render_transcript(doc,index,blocks,assets,base) if doc.get('source_format') == 'pdf' else render_document_index_page(index, blocks, assets, doc['source_url'],
                            document_index_status_label(manifest), title=doc['title'],
                            source_path=base + '/source', asset_prefix=base + '/assets/')).encode()
                        from apps.review_workbench.components.site_navigation import crumb, company_tabs
                        company = next(c for c in load_json(COMPANY_UNIVERSE_DATA)['companies'] if c['id'] == 'alphabet')
                        context = '<div class="company-context">' + crumb(company, ('材料库 / 文档目录', 'Materials / Document outline')) + company_tabs(company['id'], 'materials') + '</div>'
                        body = body.decode().replace('</nav>', '</nav>' + context, 1).encode()
                    elif suffix == '/original' and doc.get('source_format') == 'pdf':
                        body = (source / 'source.pdf').read_bytes()
                        content_type = 'application/pdf'
                    elif suffix == '/source':
                        if doc.get('source_format') == 'pdf':
                            body = render_transcript(doc,index,blocks,assets,base).encode()
                        else:
                            with gzip.open(source / 'source.html.gz', 'rt', encoding='utf-8') as stream:
                                body = render_index_source_document(stream.read(), index, blocks, assets,
                                    document_index_status_label(manifest), asset_prefix=base + '/assets/').encode()
                    elif suffix.startswith('/assets/'):
                        filename = suffix.removeprefix('/assets/')
                        if filename not in {a['filename'] for a in assets['assets']} or Path(filename).name != filename:
                            self.send_error(404)
                            return
                        body = (source / 'assets' / filename).read_bytes()
                        content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
                    else:
                        self.send_error(404)
                        return
                except (FileNotFoundError, ValueError, KeyError) as error:
                    self.send_error(503, 'Document artifacts unavailable')
                    return
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path.startswith('/companies/') or parsed.path == '/data' or parsed.path.startswith('/documents/'):
                catalog_path = ROOT / 'data/document_library/alphabet/catalog.json'
                catalog = load_catalog(ROOT) if catalog_path.exists() else {'documents': []}
                if parsed.path.startswith('/documents/'):
                    requested = parsed.path.removeprefix('/documents/')
                    doc = next((d for d in catalog['documents'] if d['id'] == requested), None)
                    if doc is None:
                        self.send_error(404, 'Unknown document')
                        return
                    if doc.get('index_folder') and doc['status'].startswith('indexed'):
                        self.send_response(303)
                        self.send_header('Location', index_url(doc))
                        self.end_headers()
                        return
                    body = render_document_status(doc).encode()
                else:
                    company_id = parsed.path.removeprefix('/companies/') if parsed.path.startswith('/companies/') else parse_qs(parsed.query).get('company', ['alphabet'])[0]
                    company = next((c for c in load_json(COMPANY_UNIVERSE_DATA)['companies'] if c['id'] == company_id), None)
                    if company is None:
                        self.send_error(404, 'Unknown company')
                        return
                    query = parse_qs(parsed.query)
                    if company_id == 'alphabet' and parsed.path != '/data' and query.get('tab', ['research'])[0] != 'data':
                        body = render_archive(company, archive.list(company=company_id), query.get('snapshot', [None])[0],
                            documents={d['id']: d for d in catalog.get('documents', [])},
                            researcher_id=query.get('researcher', [None])[0], scope=query.get('scope', [None])[0],
                            material_id=query.get('material', [None])[0]).encode()
                    else:
                        body = render_company_data(company, catalog, parsed.path == '/data' or query.get('tab') == ['data']).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/analysis":
                runs = [p for p in (ROOT / "experiments/cloud_analysis").glob("analysis-*/run.json")
                        if load_json(p).get("status") == "candidate"]
                requested = parse_qs(parsed.query).get("run", [None])[0]
                if requested:
                    runs = [p for p in runs if p.parent.name == requested]
                if not runs:
                    self.send_error(404, "No analysis run available")
                    return
                latest = max(runs, key=lambda p: load_json(p)["started_at"]).parent
                body = render_cloud_analysis(latest, ROOT).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/result" and parse_qs(parsed.query).get("view") == ["cloud-spike"]:
                runs = [p for p in (ROOT / "data/research_data/google_cloud_spike").glob("run-*/run.json")
                        if load_json(p).get("status") == "candidate" and
                        all((p.parent / name).is_file() for name in ("snapshot.json", "trace.json"))]
                if not runs:
                    self.send_error(503, "No Cloud spike run available")
                    return
                latest = max(runs, key=lambda p: load_json(p)["started_at"]).parent
                requested = parse_qs(parsed.query).get("run", [None])[0]
                if requested is not None:
                    matches = [p.parent for p in runs if p.parent.name == requested]
                    if not matches:
                        self.send_error(404, "Cloud run unavailable")
                        return
                    latest = matches[0]
                body = render_cloud_spike(latest, RAW_SOURCE_GZIP.parent).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path.startswith("/source-assets/"):
                filename = Path(parsed.path).name
                assets = load_json(DOCUMENT_ASSETS_DATA)["assets"] if DOCUMENT_ASSETS_DATA.exists() else []
                allowed = {item["filename"] for item in assets}
                target = SOURCE_ASSETS / filename
                if filename not in allowed or not target.is_file():
                    self.send_error(404)
                    return
                body = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(filename)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/source/document-index":
                required = (RAW_SOURCE_GZIP, DOCUMENT_INDEX_MANIFEST, DOCUMENT_INDEX_DATA, DOCUMENT_BLOCKS_DATA, DOCUMENT_ASSETS_DATA)
                if not all(path.exists() for path in required):
                    self.send_error(503, "Document Index candidate is unavailable")
                    return
                with gzip.open(RAW_SOURCE_GZIP, "rt", encoding="utf-8", errors="replace") as source:
                    body = render_index_source_document(
                        source.read(),
                        load_json(DOCUMENT_INDEX_DATA),
                        load_jsonl(DOCUMENT_BLOCKS_DATA),
                        load_json(DOCUMENT_ASSETS_DATA),
                        document_index_status_label(load_json(DOCUMENT_INDEX_MANIFEST)),
                    ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/source/original":
                if not RAW_SOURCE_GZIP.exists():
                    self.send_error(503, "Frozen SEC source is unavailable")
                    return
                with gzip.open(RAW_SOURCE_GZIP, "rt", encoding="utf-8", errors="replace") as source:
                    body = render_original_source_document(source.read(), load_json(SOURCE_EXCERPT)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/document-index":
                self.send_response(303)
                self.send_header('Location', '/companies/alphabet/documents/0001652044-26-000018/indexes/v0.1')
                self.end_headers()
                return
            if parsed.path == "/annotate":
                self.send_response(303)
                self.send_header("Location", "/result")
                self.end_headers()
                return
            if parsed.path not in {"/", "/result", "/benchmark"}:
                self.send_error(404)
                return
            selected = parse_qs(parsed.query).get("selected", [None])[0]
            body = render_result_page(
                load_json(data_path),
                load_json(SOURCE_EXCERPT),
                selected,
                bundle=load_json(EVIDENCE_BUNDLE_DATA),
                release_manifest=load_json(RESEARCH_DATA_MANIFEST),
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def agent_result_route(self, parsed, *, write=False):
            """Read verified results and store separately bound human evaluations."""
            host = self.headers.get('Host', '')
            origin = self.headers.get('Origin')
            if (urlparse('http://' + host).hostname not in {'localhost', '127.0.0.1', '::1'}
                    or (origin is not None and origin != 'http://' + host)
                    or self.headers.get('Sec-Fetch-Site') == 'cross-site'
                    or (write and (self.headers.get('X-Uteki-Request') != '1'
                        or self.headers.get('Content-Type', '').split(';')[0] != 'application/json'))):
                self.archive_json({'error': 'Local same-origin results only'}, 403)
                return
            from apps.review_workbench.data import agent_run_results as results
            from apps.review_workbench.data import run_scores
            from urllib.parse import unquote
            try:
                query = parse_qs(parsed.query, keep_blank_values=True)
                if any(len(values) != 1 or not values[0] for values in query.values()):
                    raise ValueError('Explicit single query values required')
                parts = [unquote(part) for part in parsed.path.strip('/').split('/')]
                if write:
                    if len(parts) != 4 or parts[3] != 'scores':
                        raise KeyError('Unknown scoring route')
                    if query:
                        raise ValueError('Scoring does not accept query parameters')
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 20000:
                        raise ValueError('Invalid request size')
                    payload = json.loads(self.rfile.read(length))
                    detail = results.load_result(ROOT, parts[2], **observation_options)
                    if detail['result_view']['kind'] == 'unavailable':
                        raise ValueError('Restore and verify result evidence before scoring')
                    value = run_scores.save_score(score_store, detail['binding'], payload)
                    self.archive_json(value, 201)
                    return
                if parsed.path == '/agent-results':
                    from apps.review_workbench.pages.agent_results import render_agent_results
                    body = render_agent_results(ROOT, query, **observation_options).encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.send_header('Referrer-Policy', 'no-referrer')
                    self.end_headers()
                    self.wfile.write(body)
                    return
                values = {key: value[0] for key, value in query.items()}
                if len(parts) == 2:
                    if set(values) - {'agent'}:
                        raise ValueError('Unknown results query')
                    value = results.list_results(ROOT, agent=values.get('agent', 'data'), **observation_options)
                elif len(parts) == 3 and parts[2] == 'compare':
                    if set(values) != {'left', 'right'}:
                        raise ValueError('Two explicit results are required')
                    value = results.compare_results(ROOT, values['left'], values['right'], **observation_options)
                elif len(parts) == 3 and not query:
                    value = results.load_result(ROOT, parts[2], **observation_options)
                elif len(parts) == 4 and parts[3] == 'scores' and not query:
                    detail = results.load_result(ROOT, parts[2], **observation_options)
                    value = run_scores.load_scores(score_store, detail['binding'])
                else:
                    raise KeyError('Unknown result route')
                self.archive_json(value)
            except run_scores.StaleScoreError:
                self.archive_json({'error': 'Result revision changed; reload the result before scoring'}, 409)
            except run_scores.CorruptScoreStoreError:
                self.archive_json({'error': 'Saved evaluations are invalid; existing records were not replaced'}, 503)
            except KeyError:
                self.archive_json({'error': 'Unknown result in the selected scope'}, 404)
            except (ValueError, TypeError):
                self.archive_json({'error': 'Result selection or evaluation is invalid; no default was substituted'}, 400)
            except OSError:
                self.archive_json({'error': 'Result or evaluation storage is unavailable'}, 503)

        def agent_run_route(self, parsed):
            """Private local observation endpoints never accept paths or write state."""
            host = self.headers.get('Host', '')
            origin = self.headers.get('Origin')
            if (urlparse('http://' + host).hostname not in {'localhost', '127.0.0.1', '::1'}
                    or (origin is not None and origin != 'http://' + host)
                    or self.headers.get('Sec-Fetch-Site') == 'cross-site'):
                self.archive_json({'error': 'Local same-origin observation only'}, 403)
                return
            from apps.review_workbench.data import agent_runs
            from urllib.parse import unquote
            try:
                query = parse_qs(parsed.query, keep_blank_values=True)
                if any(len(values) != 1 or not values[0] for values in query.values()):
                    raise ValueError('Explicit single query values required')
                if parsed.path == '/agent-runs':
                    from apps.review_workbench.pages.agent_runs import render_agent_runs
                    body = render_agent_runs(ROOT, query, **observation_options).encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.send_header('Referrer-Policy', 'no-referrer')
                    self.end_headers()
                    self.wfile.write(body)
                    return
                values = {key: value[0] for key, value in query.items()}
                def allow(*keys):
                    if set(values) - set(keys):
                        raise ValueError('Unknown observation query')
                def integer(key, default=None):
                    if key not in values:
                        return default
                    if not values[key].isdigit() or len(values[key]) > 12:
                        raise ValueError('Invalid observation number')
                    return int(values[key])
                def selected_revision():
                    value = values.get('revision')
                    if value is None:
                        return None
                    if len(value) == 64 and all(c in '0123456789abcdef' for c in value):
                        return value
                    return integer('revision')
                parts = [unquote(part) for part in parsed.path.strip('/').split('/')]
                if len(parts) == 2:
                    allow('agent', 'cursor', 'limit')
                    value = agent_runs.list_page(ROOT, agent=values.get('agent', 'data'), cursor=values.get('cursor'),
                        limit=integer('limit', 50), **observation_options)
                elif len(parts) == 3:
                    allow('revision')
                    value = agent_runs.load_run(ROOT, parts[2], revision=selected_revision(), **observation_options)
                elif len(parts) == 4 and parts[3] == 'events':
                    allow('after', 'limit')
                    value = agent_runs.read_events(ROOT, parts[2], after=values.get('after', '0'),
                        limit=integer('limit', 100), **observation_options)
                elif len(parts) == 5 and parts[3] == 'steps':
                    allow('revision')
                    value = agent_runs.load_step(ROOT, parts[2], parts[4], revision=selected_revision(), **observation_options)
                elif len(parts) == 5 and parts[3] == 'artifacts':
                    allow('revision', 'cursor', 'browse')
                    value = agent_runs.read_artifact(ROOT, parts[2], parts[4], revision=selected_revision(),
                        cursor=values.get('cursor'), browse=values.get('browse'), **observation_options)
                else:
                    raise KeyError('Unknown observation route')
                self.archive_json(value)
            except KeyError:
                self.archive_json({'error': 'Unknown run, step or artifact in the selected scope'}, 404)
            except (ValueError, TypeError):
                self.archive_json({'error': 'Observation selection or saved content is invalid; no default was substituted'}, 400)
            except OSError:
                self.archive_json({'error': 'Observation content is unavailable or still being written'}, 503)

        def log_message(self, format: str, *args) -> None:
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument('--observation-root', type=Path, help='Explicit local Agent observation store')
    parser.add_argument('--observation-output-root', type=Path, action='append', default=[],
                        help='Allowed business output parent; repeat for multiple local roots')
    parser.add_argument("--check", action="store_true", help="Check local inputs without starting the server or writing review state")
    args = parser.parse_args()
    if bool(args.observation_root) != bool(args.observation_output_root):
        parser.error('--observation-root and at least one --observation-output-root must be supplied together')
    from apps.review_workbench.workspace_check import format_report, inspect_workspace
    report = inspect_workspace(ROOT, data_path=args.data)
    if args.check or not report["ready"]:
        print(format_report(report), file=sys.stdout if report["ready"] else sys.stderr)
        if not report["ready"]:
            raise SystemExit(2)
        return
    if any(c["status"] != "ok" for c in report["checks"]):
        print(format_report(report), file=sys.stderr)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.data,
        observation_root=args.observation_root, observation_output_roots=args.observation_output_root))
    print(f'Uteki Agent results: http://{args.host}:{args.port}/agent-results')
    print(f'Uteki Agent process: http://{args.host}:{args.port}/agent-runs')
    server.serve_forever()


if __name__ == "__main__":
    main()
