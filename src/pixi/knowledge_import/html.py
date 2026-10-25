"""Small dependency-free HTML-to-text extraction for offline documentation."""

import re
from html.parser import HTMLParser


class _TextParser(HTMLParser):
    _hidden = {"script", "style", "nav", "noscript", "template"}
    _blocks = {
        "address",
        "article",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tr",
        "ul",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden: list[str] = []
        self.pre_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._hidden:
            self.hidden.append(tag)
        if self.hidden:
            return
        if tag in self._blocks:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append("\t")
        if tag == "pre":
            self.pre_depth += 1

    def handle_endtag(self, tag):
        if self.hidden:
            if tag in self.hidden:
                del self.hidden[len(self.hidden) - 1 - self.hidden[::-1].index(tag) :]
            return
        if tag == "pre":
            self.pre_depth = max(0, self.pre_depth - 1)
        if tag in self._blocks:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data if self.pre_depth else re.sub(r"\s+", " ", data))


def html_to_text(html: str) -> str:
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts).strip()
