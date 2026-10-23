"""Source-preserving HTML views shared by parsing and exact evidence readback."""
from __future__ import annotations

import re

from lxml import etree, html

from ..contracts.common import CatalogError, digest
from ..contracts.evidence import HtmlLocator


# 统一 HTML 标签大小写；注释等非元素节点返回空字符串。
def tag(node):
    return str(node.tag).lower() if isinstance(node.tag, str) else ""


# 将连续空白折叠成单个空格，作为定位和哈希共用的文本投影规则。
def normalize(text):
    return " ".join(text.split())


# 用 DOM 路径生成不支持的 srcset 资源键，使采集与解析记录同一个显式缺口。
def srcset_key(path):
    return "unsupported-srcset-" + digest(path.encode())


# 沿节点及祖先检查非正文、导航与显式隐藏标记，返回第一条排除原因。
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


# 递归提取受支持的可见文本；子节点被排除时仍保留属于父节点的 tail 文本。
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


# 从冻结 HTML 构造确定的节点视图，统一文本抽取、DOM 路径及证据精确回读。
class SourceDOM:
    # 严格检查 UTF-8 原始字节和完整文档标记，再用禁网解析器建树并保留修复诊断。
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
        # 同一 id 保留全部匹配节点，后续表头、脚注和 XBRL 引用据此识别歧义。
        self.by_id = {}
        for node in self.nodes:
            if tag(node) and node.get("id"):
                self.by_id.setdefault(node.get("id"), []).append(node)
        # 脚注锚点兼容 id 与旧式 a[name]；重复锚点保持多候选，不擅自挑选目标。
        self.by_anchor = {key:list(value) for key,value in self.by_id.items()}
        for node in self.nodes:
            if tag(node) == "a" and node.get("name"):
                values = self.by_anchor.setdefault(node.get("name"), [])
                if node not in values:
                    values.append(node)
        # HTML recovery diagnostics are observable; no claim of XML validity.
        self.diagnostics = tuple(sorted({str(e.type_name) for e in parser.error_log}))

    # 返回当前源 DOM 中节点的 XPath，作为版本内定位依据。
    def path(self, node):
        return self.tree.getpath(node)

    # 按指定投影提取文本并统一空白；raw 投影用于保留 Inline XBRL 等原始节点内容。
    def text(self, node, projection="visible_text_v1"):
        return normalize(visible_text(node) if projection == "visible_text_v1" else node.text_content())

    # 为整个节点文本建立字符区间和文本哈希；区间坐标属于规范化投影而非原始字节。
    def locator(self, node, *, raw=False):
        projection = "raw_text_v1" if raw else "visible_text_v1"
        value = self.text(node, projection)
        return HtmlLocator(kind="html_node", projection=projection, dom_path=self.path(node),
                           char_start=0, char_end=len(value), text_sha256=digest(value.encode()))

    # 从冻结 DOM 回读定位区间，并校验范围和文本哈希，防止错位引用静默通过。
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

    # 导出节点 HTML 结构且排除相邻 tail，用于保留尚不能语义化的原始结构。
    def snippet(self, node):
        return etree.tostring(node, encoding="unicode", method="html", with_tail=False)
