"""Server-rendered company research workbench.

Legacy import aliases retain module identity for existing integrations and patches.
New code uses pages, components, and data directly.
"""
from importlib import import_module
import sys

_LEGACY_MODULES = {'acceptance_view': 'pages.acceptance_view',
 'cloud_analysis': 'pages.cloud_analysis',
 'cloud_spike': 'pages.cloud_spike',
 'company_brief': 'pages.company_brief',
 'company_data': 'pages.company_data',
 'company_universe': 'pages.company_universe',
 'dataset_view': 'pages.dataset_view',
 'document_index': 'pages.document_index',
 'earnings_reader': 'pages.earnings_reader',
 'query_runs': 'pages.query_runs',
 'research_archive_ui': 'pages.research_archive_ui',
 'archive_navigation': 'components.archive_navigation',
 'citation_translations': 'components.citation_translations',
 'report_text': 'components.report_text',
 'site_navigation': 'components.site_navigation',
 'visual_system': 'components.visual_system',
 'document_library': 'data.document_library',
 'research_archive_import': 'data.research_archive_import'}

for _old, _new in _LEGACY_MODULES.items():
    _module = import_module(f"{__name__}.{_new}")
    sys.modules[f"{__name__}.{_old}"] = _module
    globals()[_old] = _module
