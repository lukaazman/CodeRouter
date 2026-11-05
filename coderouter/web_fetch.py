"""User-initiated page fetch for read-only context (`/fetch <url>`)."""

import html
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

FETCH_MAX_BYTES = 512 * 1024
FETCH_MAX_TEXT_CHARS = 60 * 1024
FETCH_TIMEOUT_SECONDS = 15
SKIP_TAGS = {"script", "style", "noscript", "svg", "head", "nav", "footer", "form"}
BLOCK_TAGS = {"p", "div", "section", "article", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "table"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip, self.title, self._in_title = [], 0, "", False

    def handle_starttag(self, tag, _attrs):
        if tag in SKIP_TAGS:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in BLOCK_TAGS:
            self.parts.append("\n")
        if tag in {"h1", "h2", "h3"}:
            self.parts.append("#" * int(tag[1]) + " ")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if not self.skip:
            self.parts.append(data)


def html_to_text(markup):
    parser = _TextExtractor()
    parser.feed(markup)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return parser.title.strip(), html.unescape(text).strip()


def validate_url(url):
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Only http(s) URLs can be fetched.")
    return parsed.geturl()


def fetch_text(url, opener=urlopen):
    url = validate_url(url)
    request = Request(url, headers={"User-Agent": "CodeRouter/1.0 (+local desktop app)", "Accept": "text/html,text/plain,*/*"})
    with opener(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        content_type = response.headers.get("Content-Type", "") if getattr(response, "headers", None) else ""
        raw = response.read(FETCH_MAX_BYTES + 1)
    truncated = len(raw) > FETCH_MAX_BYTES
    charset = "utf-8"
    match = re.search(r"charset=([\w-]+)", content_type or "")
    if match:
        charset = match.group(1)
    body = raw[:FETCH_MAX_BYTES].decode(charset, errors="replace")
    if "html" in content_type.lower() or body.lstrip().lower().startswith(("<!doctype", "<html")):
        title, text = html_to_text(body)
    else:
        title, text = "", body
    text = text[:FETCH_MAX_TEXT_CHARS]
    if truncated or len(text) >= FETCH_MAX_TEXT_CHARS:
        text += "\n\n(truncated)"
    return title or url, text


def save_fetched(directory, url, title, text):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", urlparse(url).netloc.lower() + urlparse(url).path.lower()).strip("-")[:60] or "page"
    path = directory / f"{slug}.md"
    path.write_text(f"# {title}\n\nSource: {url}\n\n{text}\n", encoding="utf-8")
    return path
