"""Content builder for Blogger publishing (Phase 5C).

Converts article markdown body to Blogger-safe HTML, embeds images with
attribution, appends source references, and sanitizes the output.

The markdown renderer is a direct Python port of frontend/src/lib/markdown.ts
to keep frontend preview and published output consistent. No external markdown
library is needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape as _html_escape


# --- HTML escaping and URL safety ------------------------------------------


def escape_html(value: str) -> str:
    """Escape HTML special characters. Port of frontend escapeHtml."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# Dangerous URL schemes that must never appear in href/src attributes.
_DANGEROUS_SCHEMES = re.compile(
    r"^\s*(javascript|data|vbscript|file|blob|ftp|telnet|ssh):",
    re.IGNORECASE,
)


def safe_url(value: str | None) -> str | None:
    """Return the URL if safe (http/https/mailto or scheme-less), else None.

    Port of frontend safeUrl with additional dangerous-scheme rejection.
    """
    if not value:
        return None
    trimmed = value.strip()
    if _DANGEROUS_SCHEMES.match(trimmed):
        return None
    if re.match(r"^https?://", trimmed, re.IGNORECASE):
        return trimmed
    if re.match(r"^mailto:", trimmed, re.IGNORECASE):
        return trimmed
    if ":" not in trimmed:
        return trimmed
    return None


# --- Inline markdown --------------------------------------------------------


def _inline_markdown(value: str) -> str:
    """Convert inline markdown (bold, italic, code, links) to HTML.

    Port of frontend inlineMarkdown.
    """
    # Bold: **text**
    value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
    # Italic: *text*
    value = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", value)
    # Inline code: `text`
    value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    # Links: [text](url)
    value = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda m: _render_link(m.group(1), m.group(2)),
        value,
    )
    return value


def _render_link(text: str, url: str) -> str:
    """Render a markdown link, sanitizing the URL."""
    safe = safe_url(url)
    if safe:
        return f'<a href="{safe}" target="_blank" rel="noopener noreferrer">{text}</a>'
    # Dangerous URL: render as plain text with the URL in parentheses
    return f"{text} ({url})"


# --- Block-level markdown ---------------------------------------------------


def markdown_to_html(markdown: str) -> str:
    """Convert markdown text to HTML. Port of frontend renderMarkdown.

    Handles: headings, paragraphs, unordered lists, fenced code blocks,
    blockquotes, and inline formatting. All raw HTML in the input is escaped.
    """
    if not markdown:
        return ""

    lines = markdown.replace("\r\n", "\n").split("\n")
    html: list[str] = []
    para: list[str] = []
    in_list = False
    in_code = False

    def flush_para() -> None:
        if para:
            html.append(f"<p>{_inline_markdown(escape_html(' '.join(para)))}</p>")
            para.clear()

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            html.append("</ul>")
            in_list = False

    for raw in lines:
        # Fenced code block toggle
        if raw.strip().startswith("```"):
            flush_para()
            close_list()
            if in_code:
                html.append("</code></pre>")
                in_code = False
            else:
                html.append("<pre><code>")
                in_code = True
            continue

        # Inside code block: escape and output verbatim
        if in_code:
            html.append(escape_html(raw))
            continue

        trimmed = raw.strip()

        # Blank line: flush paragraph and close list
        if trimmed == "":
            flush_para()
            close_list()
            continue

        # Headings: # ... ######
        heading = re.match(r"^(#{1,6})\s+(.*)$", trimmed)
        if heading:
            flush_para()
            close_list()
            level = len(heading.group(1))
            text = _inline_markdown(escape_html(heading.group(2)))
            html.append(f"<h{level}>{text}</h{level}>")
            continue

        # Unordered list items: - item or * item
        list_item = re.match(r"^[-*]\s+(.*)$", trimmed)
        if list_item:
            flush_para()
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{_inline_markdown(escape_html(list_item.group(1)))}</li>")
            continue

        # Blockquotes: > text
        if trimmed.startswith(">"):
            flush_para()
            close_list()
            content = re.sub(r"^>\s?", "", trimmed)
            html.append(f"<blockquote>{_inline_markdown(escape_html(content))}</blockquote>")
            continue

        # Regular paragraph text
        para.append(raw)

    flush_para()
    close_list()
    if in_code:
        html.append("</code></pre>")

    return "\n".join(html)


# --- Content builder --------------------------------------------------------


@dataclass
class ImageRef:
    """Simplified image reference for content building."""

    url: str
    alt: str = ""
    caption: str = ""
    attribution: str = ""
    license: str = ""


@dataclass
class SourceRef:
    """Simplified source reference for content building."""

    title: str
    url: str
    provider: str = ""
    snippet: str = ""


def _render_image(img: ImageRef) -> str:
    """Render a single image as Blogger-safe HTML."""
    src = safe_url(img.url)
    if not src:
        return ""
    alt = escape_html(img.alt)
    parts = [f'<img src="{src}" alt="{alt}" style="max-width:100%;height:auto;" />']
    if img.caption:
        parts.append(f"<p><em>{escape_html(img.caption)}</em></p>")
    if img.attribution:
        parts.append(f"<p><small>{escape_html(img.attribution)}</small></p>")
    return "\n".join(parts)


def _render_sources(sources: list[SourceRef]) -> str:
    """Render a 'Sources' section at the end of the article."""
    if not sources:
        return ""
    items = []
    for s in sources:
        url = safe_url(s.url)
        title = escape_html(s.title)
        if url:
            items.append(f'<li><a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a></li>')
        else:
            items.append(f"<li>{title}</li>")
    return (
        "<h2>Sources</h2>\n<ul>\n"
        + "\n".join(items)
        + "\n</ul>"
    )


def build_post_html(
    title: str,
    body: str,
    *,
    images: list[ImageRef] | None = None,
    sources: list[SourceRef] | None = None,
) -> str:
    """Build the full HTML content for a Blogger post.

    Combines the article title, converted markdown body, embedded images
    (sorted by position), and a sources section. Output is Blogger-safe HTML.

    This does NOT wrap in <html>/<head>/<body> — Blogger expects just the
    post content fragment.
    """
    parts: list[str] = []

    # Article title as H1
    if title:
        parts.append(f"<h1>{escape_html(title)}</h1>")

    # Main body: markdown -> HTML
    body_html = markdown_to_html(body)
    if body_html:
        parts.append(body_html)

    # Images (sorted by insertion order / position)
    if images:
        for img in images:
            rendered = _render_image(img)
            if rendered:
                parts.append(rendered)

    # Sources section
    sources_html = _render_sources(sources or [])
    if sources_html:
        parts.append(sources_html)

    return "\n\n".join(parts)


# --- HTML sanitization ------------------------------------------------------


# Tags and attributes we allow in the final output. Everything else is stripped.
_ALLOWED_TAGS = frozenset(
    {
        "h1", "h2", "h3", "h4", "h5", "h6",
        "p", "br", "hr",
        "strong", "em", "b", "i", "u",
        "a", "img",
        "ul", "ol", "li",
        "blockquote",
        "pre", "code",
        "table", "thead", "tbody", "tr", "th", "td",
        "small", "figure", "figcaption",
        "div", "span",
    }
)

_ALLOWED_ATTRS = {
    "a": {"href", "target", "rel", "title"},
    "img": {"src", "alt", "width", "height", "style", "title"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}

# Attribute values that could execute code
_DANGEROUS_ATTR_VALUES = re.compile(
    r"(javascript|data|vbscript)\s*:", re.IGNORECASE
)

_TAG_RE = re.compile(r"<(/?)(\w+)([^>]*)>")
_ATTR_RE = re.compile(r'(\w[\w-]*)(?:\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+)))?')


def sanitize_html(html: str) -> str:
    """Final sanitization pass for Blogger-safe HTML.

    Strips disallowed tags, removes dangerous attributes (onclick, style with
    expressions, etc.), and ensures all URLs are safe.

    This is a lightweight sanitizer for our own generated content — not a
    general-purpose XSS filter. The input is already escaped markdown output.
    """
    if not html:
        return ""

    def _replace_tag(m: re.Match) -> str:
        is_close = m.group(1) == "/"
        tag = m.group(2).lower()
        attrs_str = m.group(3)

        if tag not in _ALLOWED_TAGS:
            return ""

        if is_close:
            return f"</{tag}>"

        # Parse attributes
        attrs: dict[str, str] = {}
        for attr_match in _ATTR_RE.finditer(attrs_str):
            name = attr_match.group(1).lower()
            value = attr_match.group(2) or attr_match.group(3) or attr_match.group(4) or ""

            # Check if this attribute is allowed for this tag
            allowed = _ALLOWED_ATTRS.get(tag, set())
            if name not in allowed:
                continue

            # Check for dangerous values
            if _DANGEROUS_ATTR_VALUES.search(value):
                continue

            # Sanitize URL attributes
            if name in ("href", "src"):
                safe = safe_url(value)
                if safe is None:
                    continue
                value = safe

            # Escape attribute values
            value = value.replace("&", "&amp;").replace('"', "&quot;")
            attrs[name] = value

        # Build tag string
        attr_str = "".join(f' {k}="{v}"' for k, v in attrs.items())
        return f"<{tag}{attr_str}>"

    result = _TAG_RE.sub(_replace_tag, html)
    # Also strip HTML comments
    result = re.sub(r"<!--.*?-->", "", result, flags=re.DOTALL)
    return result
