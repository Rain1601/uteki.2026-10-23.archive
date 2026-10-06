from __future__ import annotations

import hashlib
import re
import urllib.request
from html.parser import HTMLParser

from uteki.domain.documents import Document, Paragraph


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def text_hash(value: str) -> str:
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


class _BlockParser(HTMLParser):
    block_tags = {"div", "p", "li", "td"}
    ignored_tags = {"script", "style", "ix:header"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._block_depth = 0
        self._parts: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.ignored_tags:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag in self.block_tags:
            if self._block_depth == 0:
                self._parts = []
            self._block_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self.ignored_tags and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth or tag not in self.block_tags or self._block_depth == 0:
            return
        self._block_depth -= 1
        if self._block_depth == 0:
            value = normalize_text(" ".join(self._parts))
            if value:
                self.blocks.append(value)
            self._parts = []

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and self._block_depth:
            self._parts.append(data)


def parse_sec_html(document_id: str, source_url: str, raw_html: bytes) -> Document:
    parser = _BlockParser()
    parser.feed(raw_html.decode("utf-8", errors="replace"))
    paragraphs: list[Paragraph] = []
    previous: str | None = None
    for value in parser.blocks:
        if value == previous:
            continue
        previous = value
        paragraphs.append(Paragraph(len(paragraphs) + 1, value, text_hash(value)))
    return Document(
        id=document_id,
        source_url=source_url,
        content_hash=hashlib.sha256(raw_html).hexdigest(),
        paragraphs=tuple(paragraphs),
    )


class SecFilingSource:
    def __init__(self, user_agent: str) -> None:
        if not user_agent.strip():
            raise ValueError("SEC user agent must not be empty")
        self.user_agent = user_agent

    def fetch(self, document_id: str, source_url: str, timeout: float = 30.0) -> Document:
        request = urllib.request.Request(source_url, headers={"User-Agent": self.user_agent})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return parse_sec_html(document_id, source_url, response.read())

