"""Shared presentation for workbench pages, never applied to source documents."""
from apps.review_workbench.assets import asset_text
from functools import wraps
from pathlib import Path
import re


def theme_html(page: str, area: str) -> str:
    if 'id="uteki-visual-system"' in page:
        return page
    if not re.fullmatch(r'[a-z-]+', area):
        raise ValueError('Invalid workbench area')
    style = '<style id="uteki-visual-system">' + asset_text('design_tokens.css') + '\n' + asset_text('visual_system.css') + '</style>'
    if re.search(r'<body\b', page, re.I):
        page = re.sub(r'<body\b', f'<body data-workbench="{area}"', page, count=1, flags=re.I)
        # Some older templates omit head tags. Insert before their body as well.
        pos = re.search(r'</head\s*>|<body\b', page, re.I).start()
        return add_navigation(page[:pos] + style + page[pos:])
    # Legacy data/experiment pages use HTML's implicit body. Make it explicit
    # without reserializing scripts, source fragments, or historical artifacts.
    match = re.search(r'<header\b|<h1\b|<main\b', page, re.I)
    pos = match.start() if match else len(page)
    return add_navigation(page[:pos] + style + f'<body data-workbench="{area}">' + page[pos:])


def workbench_page(area):
    def decorate(render):
        @wraps(render)
        def themed(*args, **kwargs):
            return theme_html(render(*args, **kwargs), area)
        return themed
    return decorate


def add_navigation(page):
    header = '<nav id="site-navigation" aria-label="Global navigation"><a class="site-brand" href="/">Uteki</a><a href="/" data-global-page="home"><span lang="zh">主页</span><span lang="en">Home</span></a><a href="/companies" data-global-page="companies"><span lang="zh">公司</span><span lang="en">Companies</span></a><a href="/evaluation" data-global-page="evaluation"><span lang="zh">数据评估</span><span lang="en">Data evaluation</span></a></nav>'
    header += ("""<script>""" + asset_text('global_navigation.js') + """</script>""")
    match = re.search(r'<body\b[^>]*>', page, re.I)
    if not match: return page
    return page[:match.end()] + header + page[match.end():]
