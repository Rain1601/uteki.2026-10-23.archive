import copy
import gzip
import hashlib
import unittest

from apps.review_workbench.app import (
    COMPANY_UNIVERSE_DATA,
    DEFAULT_DATA,
    EVIDENCE_BUNDLE_DATA,
    RAW_SOURCE_GZIP,
    DOCUMENT_ASSETS_DATA,
    DOCUMENT_BLOCKS_DATA,
    DOCUMENT_INDEX_DATA,
    DOCUMENT_INDEX_MANIFEST,
    RESEARCH_DATA_MANIFEST,
    SOURCE_MANIFEST,
    SOURCE_EXCERPT,
    evidence_bundle_views,
    load_json,
    document_index_status_label,
    parent_and_children,
    render_original_source_document,
    render_result_page,
    validate_claims,
)
from apps.review_workbench.document_index import (
    load_jsonl,
    render_document_index_page,
    render_index_source_document,
)


class ReviewWorkbenchTests(unittest.TestCase):
    def test_v2_unresolved_relationships_cannot_become_legacy_hierarchy(self):
        data = dict(self.data, schema_version='business-map-v0.2')
        with self.assertRaisesRegex(ValueError, 'v2_display_requires_basis_aware_renderer'):
            parent_and_children(data)

    def setUp(self) -> None:
        self.data = load_json(DEFAULT_DATA)
        self.bundle = load_json(EVIDENCE_BUNDLE_DATA)
        self.manifest = load_json(RESEARCH_DATA_MANIFEST)
        self.claims, self.spans = evidence_bundle_views(self.bundle)
        self.excerpt = load_json(SOURCE_EXCERPT)

    def test_every_claim_resolves_to_fixed_source_evidence(self) -> None:
        validate_claims(self.data, self.claims, self.excerpt, self.spans)
        self.assertEqual(len(self.claims["claims"]), 57)
        self.assertEqual(len(self.spans["spans"]), 80)
        self.assertTrue(all(item.get("translation_zh") for item in self.excerpt["paragraphs"]))

    def test_rejects_claim_with_unknown_evidence(self) -> None:
        claims = copy.deepcopy(self.claims)
        claims["claims"][0]["evidence_ids"] = ["missing"]
        with self.assertRaisesRegex(ValueError, "unknown evidence"):
            validate_claims(self.data, claims, self.excerpt)

    def test_result_page_renders_field_level_knowledge_and_evidence_previews(self) -> None:
        page = render_result_page(self.data, self.excerpt, "google-advertising", self.claims)
        self.assertIn("Structured research data", page)
        self.assertIn("结构化研究数据", page)
        self.assertIn("data-claim='advertising-definition'", page)
        self.assertIn("data-ordinal='773'", page)
        self.assertIn("<b>4 <span data-lang='en'>sources</span><span data-lang='zh'>条证据</span>", page)
        self.assertIn("Google Search &amp; other · YouTube ads · Google Network", page)
        self.assertIn("1/4", page)
        self.assertIn("4/4", page)
        self.assertIn("data-select='google-search-other'", page)
        self.assertIn("Data Agent result", page)
        self.assertIn("Data Agent 解析结果", page)
        self.assertIn("Data candidate v0.2", page)
        self.assertIn("Business Map v0.3-candidate", page)
        self.assertIn("57 <span data-lang='en'>claims</span><span data-lang='zh'>条 Claims</span>", page)
        self.assertIn("13 <span data-lang='en'>metrics</span><span data-lang='zh'>项 Metrics</span>", page)
        self.assertIn("80 <span data-lang='en'>evidence</span><span data-lang='zh'>条 Evidence</span>", page)
        self.assertIn(self.bundle["data_snapshot_id"], page)
        self.assertIn(self.bundle["bundle_id"], page)
        self.assertIn("data-select='google-subscriptions'", page)
        self.assertIn("data-select='google-platforms'", page)
        self.assertIn("data-select='google-devices'", page)
        self.assertIn("data-select='google-spd-revenue'", page)

    def test_result_reads_the_published_data_agent_release(self) -> None:
        self.assertEqual(DEFAULT_DATA.parent, EVIDENCE_BUNDLE_DATA.parent)
        self.assertEqual(DEFAULT_DATA.parent, RESEARCH_DATA_MANIFEST.parent)
        self.assertEqual(self.data["schema_version"], self.bundle["business_map_version"].removeprefix("v"))
        self.assertEqual(len(self.bundle["claims"]), self.manifest["counts"]["claims"])
        self.assertEqual(len(self.bundle["metrics"]), self.manifest["counts"]["metrics"])
        self.assertEqual(len(self.bundle["evidence_links"]), self.manifest["counts"]["evidence_links"])

    def test_cross_view_support_edges_do_not_change_tree_parentage(self) -> None:
        _, children = parent_and_children(self.data)
        business_nodes = {"google-subscriptions", "google-platforms", "google-devices"}

        self.assertTrue(business_nodes.issubset(set(children["google-services"])))
        self.assertEqual(children.get("google-spd-revenue", []), [])

    def test_chinese_mode_keeps_translation_and_sec_original(self) -> None:
        page = render_result_page(self.data, self.excerpt, claims_data=self.claims)
        self.assertIn("中文为忠实翻译候选", page)
        self.assertIn("就报告目的而言，Google 由 Google Services", page)
        self.assertIn("SEC 英文原文", page)
        self.assertIn("For reporting purposes Google comprises two segments", page)

    def test_source_supports_independent_original_and_structured_views(self) -> None:
        page = render_result_page(self.data, self.excerpt, claims_data=self.claims)
        self.assertIn("data-view='original'", page)
        self.assertIn("data-view='structured'", page)
        self.assertIn("src='/source/original'", page)
        self.assertIn("同一条证据，两种阅读方式。", page)
        self.assertIn("data-paragraph='55'", page)
        self.assertIn("data-paragraph='792'", page)

    def test_original_source_keeps_html_layout_and_adds_translation_bridge(self) -> None:
        raw = "<html><head><title>SEC</title></head><body><table><tr><td>Revenue</td><td>42</td></tr></table></body></html>"
        rendered = render_original_source_document(raw, self.excerpt)
        self.assertIn("<table><tr><td>Revenue</td><td>42</td></tr></table>", rendered)
        self.assertIn("uteki-source-bridge", rendered)
        self.assertIn("translation_zh", rendered)
        self.assertIn("中文证据译文", rendered)

    def test_frozen_source_matches_manifest_hash(self) -> None:
        manifest = load_json(RAW_SOURCE_GZIP.parent / "manifest.json")
        with gzip.open(RAW_SOURCE_GZIP, "rb") as source:
            raw = source.read()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), manifest["content_sha256"])
        self.assertEqual(len(raw), manifest["raw_document_bytes"])

    def test_document_index_is_a_separate_bilingual_read_only_page(self) -> None:
        index = load_json(DOCUMENT_INDEX_DATA)
        blocks = load_jsonl(DOCUMENT_BLOCKS_DATA)
        assets = load_json(DOCUMENT_ASSETS_DATA)
        label = document_index_status_label(load_json(DOCUMENT_INDEX_MANIFEST))
        page = render_document_index_page(index, blocks, assets, load_json(SOURCE_MANIFEST)["source_url"], label)
        self.assertIn("Document Navigator", page)
        self.assertIn("Index v0.1 · Frozen", page)
        self.assertIn("只显示法定结构", page)
        self.assertIn("原始版式", page)
        self.assertIn("结构化 Blocks", page)
        self.assertIn("src='/source/document-index'", page)
        self.assertEqual(page.count("class='index-node'"), 28)

    def test_document_index_source_keeps_original_html_and_adds_node_bridge(self) -> None:
        index = load_json(DOCUMENT_INDEX_DATA)
        blocks = load_jsonl(DOCUMENT_BLOCKS_DATA)
        assets = load_json(DOCUMENT_ASSETS_DATA)
        label = document_index_status_label(load_json(DOCUMENT_INDEX_MANIFEST))
        with gzip.open(RAW_SOURCE_GZIP, "rt", encoding="utf-8", errors="replace") as source:
            raw = source.read()
        rendered = render_index_source_document(raw, index, blocks, assets, label)
        self.assertIn("uteki-index-source-bridge", rendered)
        self.assertIn("uteki-index-focus", rendered)
        self.assertIn("goog-20251231_g1.jpg", rendered)
        self.assertIn("Index v0.1 · Frozen", rendered)

    def test_company_universe_candidate_is_available(self) -> None:
        universe = load_json(COMPANY_UNIVERSE_DATA)
        self.assertEqual(universe["schema_version"], "company-universe-v0.1-candidate")
        self.assertEqual(len(universe["companies"]), 50)


if __name__ == "__main__":
    unittest.main()
