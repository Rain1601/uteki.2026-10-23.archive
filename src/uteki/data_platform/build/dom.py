"""Source-preserving HTML views shared by parsing and exact evidence readback."""
from __future__ import annotations

import re

from lxml import etree, html

from ..contracts.common import CatalogError, digest
from ..contracts.evidence import HtmlLocator


def tag(node):
    return str(node.tag).lower() if isinstance(node.tag, str) else ""


def normalize(text):
    return " ".join(text.split())


def srcset_key(path):
    return "unsupported-srcset-" + digest(path.encode())


def excluded(node):
    for item in (node, *node.iterancestors()):
        name = tag(item)
        if name in {"head", "script", "style", "noscript", "ix:hidden", "ix:header"}:
            return "non_visible:" + name
        if name in {"nav", "header", "footer"}:
            return "navigation:" + name
        if "hidden" in item.attrib or item.get("aria-hidden", "").lower() == "true":
            return "hidden_attribute"
        if re.search(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\s*(?:!important\s*)?(?:;|$)", item.get("style", ""), re.I):
            return "hidden_inline_style"
    return None


def visible_text(node):
    if not tag(node) or excluded(node):
        return ""
    if tag(node) == "br":
        return "\n"
    parts = [node.text or ""]
    for child in node:
        parts.append(visible_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


class SourceDOM:
    def __init__(self, raw: bytes, *, encoding: str):
        if not isinstance(raw, bytes) or not raw or encoding != "utf-8":
            raise CatalogError("PARSE_FAILED", "nonempty bytes and supported explicit utf-8 encoding required")
        try:
            raw.decode(encoding, errors="strict")
            if not re.search(br"<html(?:\s|>)", raw, re.I) or not re.search(br"<body(?:\s|>)", raw, re.I):
                raise ValueError("complete HTML document required")
            parser = html.HTMLParser(encoding=encoding, no_network=True, recover=True, remove_comments=False)
            self.root = html.document_fromstring(raw, parser=parser)
        except (UnicodeError, ValueError, etree.LxmlError) as error:
            raise CatalogError("PARSE_FAILED", "invalid or unsupported HTML input") from error
        self.tree = self.root.getroottree()
        if self.root.xpath('//base[@href]'):
            raise CatalogError("PARSE_FAILED", "HTML base href is not supported by this source policy version")
        self.nodes = list(self.root.iter())
        self.paths = {self.tree.getpath(n): n for n in self.nodes if tag(n)}
        self.by_id = {}
        for node in self.nodes:
            if tag(node) and node.get("id"):
                self.by_id.setdefault(node.get("id"), []).append(node)
        self.by_anchor = {key:list(value) for key,value in self.by_id.items()}
        for node in self.nodes:
            if tag(node) == "a" and node.get("name"):
                values = self.by_anchor.setdefault(node.get("name"), [])
                if node not in values:
                    values.append(node)
        # HTML recovery diagnostics are observable; no claim of XML validity.
        self.diagnostics = tuple(sorted({str(e.type_name) for e in parser.error_log}))

    def path(self, node):
        return self.tree.getpath(node)

    def text(self, node, projection="visible_text_v1"):
        return normalize(visible_text(node) if projection == "visible_text_v1" else node.text_content())

    def locator(self, node, *, raw=False):
        projection = "raw_text_v1" if raw else "visible_text_v1"
        value = self.text(node, projection)
        return HtmlLocator(kind="html_node", projection=projection, dom_path=self.path(node),
                           char_start=0, char_end=len(value), text_sha256=digest(value.encode()))

    def resolve(self, locator: HtmlLocator):
        locator = HtmlLocator.model_validate(locator)
        node = self.paths.get(locator.dom_path)
        if node is None:
            raise CatalogError("INVALID_LOCATOR", "node is not in the frozen HTML document")
        text = self.text(node, locator.projection)
        if locator.char_end > len(text):
            raise CatalogError("INVALID_LOCATOR", "text range exceeds frozen node")
        value = text[locator.char_start:locator.char_end]
        if digest(value.encode()) != locator.text_sha256:
            raise CatalogError("INVALID_LOCATOR", "text hash differs from frozen node range")
        return node, value

    def snippet(self, node):
        return etree.tostring(node, encoding="unicode", method="html", with_tail=False)
