"""Tests for the publish content builder (Phase 5C).

Covers: markdown conversion, image embedding, source rendering,
HTML sanitization, XSS prevention, and edge cases.
"""

import pytest

from pipeline.publish import (
    ImageRef,
    SourceRef,
    build_post_html,
    escape_html,
    markdown_to_html,
    safe_url,
    sanitize_html,
)


# --- escape_html ------------------------------------------------------------


class TestEscapeHtml:
    def test_basic(self):
        assert escape_html("hello") == "hello"

    def test_special_chars(self):
        assert escape_html('<div class="x">&</div>') == (
            "&lt;div class=&quot;x&quot;&gt;&amp;&lt;/div&gt;"
        )

    def test_single_quote_preserved(self):
        # Single quotes are not escaped — they're safe inside double-quoted attrs
        assert escape_html("it's") == "it's"

    def test_empty(self):
        assert escape_html("") == ""


# --- safe_url ---------------------------------------------------------------


class TestSafeUrl:
    def test_https(self):
        assert safe_url("https://example.com") == "https://example.com"

    def test_http(self):
        assert safe_url("http://example.com") == "http://example.com"

    def test_mailto(self):
        assert safe_url("mailto:user@example.com") == "mailto:user@example.com"

    def test_relative(self):
        assert safe_url("/path/to/page") == "/path/to/page"

    def test_anchor(self):
        assert safe_url("#section") == "#section"

    def test_javascript(self):
        assert safe_url("javascript:alert(1)") is None

    def test_data(self):
        assert safe_url("data:text/html;base64,PHNjcmlwdD4=") is None

    def test_vbscript(self):
        assert safe_url("vbscript:MsgBox(1)") is None

    def test_file(self):
        assert safe_url("file:///etc/passwd") is None

    def test_blob(self):
        assert safe_url("blob:https://example.com/id") is None

    def test_ftp(self):
        assert safe_url("ftp://example.com") is None

    def test_telnet(self):
        assert safe_url("telnet://example.com") is None

    def test_empty(self):
        assert safe_url("") is None

    def test_none(self):
        assert safe_url(None) is None

    def test_whitespace(self):
        assert safe_url("  https://example.com  ") == "https://example.com"

    def test_javascript_with_whitespace(self):
        assert safe_url("  javascript:alert(1)  ") is None


# --- markdown_to_html -------------------------------------------------------


class TestMarkdownToHtml:
    def test_empty(self):
        assert markdown_to_html("") == ""

    def test_none_like(self):
        assert markdown_to_html("") == ""

    def test_paragraph(self):
        html = markdown_to_html("Hello world.")
        assert html == "<p>Hello world.</p>"

    def test_multiple_paragraphs(self):
        html = markdown_to_html("First paragraph.\n\nSecond paragraph.")
        assert "<p>First paragraph.</p>" in html
        assert "<p>Second paragraph.</p>" in html

    def test_heading_h1(self):
        html = markdown_to_html("# Title")
        assert html == "<h1>Title</h1>"

    def test_heading_h2(self):
        html = markdown_to_html("## Section")
        assert html == "<h2>Section</h2>"

    def test_heading_h3(self):
        html = markdown_to_html("### Subsection")
        assert html == "<h3>Subsection</h3>"

    def test_heading_h4(self):
        html = markdown_to_html("#### Detail")
        assert html == "<h4>Detail</h4>"

    def test_heading_h5(self):
        html = markdown_to_html("##### Fine")
        assert html == "<h5>Fine</h5>"

    def test_heading_h6(self):
        html = markdown_to_html("###### Finest")
        assert html == "<h6>Finest</h6>"

    def test_bold(self):
        html = markdown_to_html("**bold text**")
        assert "<strong>bold text</strong>" in html

    def test_italic(self):
        html = markdown_to_html("*italic text*")
        assert "<em>italic text</em>" in html

    def test_inline_code(self):
        html = markdown_to_html("Use `code` here.")
        assert "<code>code</code>" in html

    def test_unordered_list(self):
        html = markdown_to_html("- item one\n- item two")
        assert "<ul>" in html
        assert "<li>item one</li>" in html
        assert "<li>item two</li>" in html
        assert "</ul>" in html

    def test_unordered_list_asterisk(self):
        html = markdown_to_html("* alpha\n* beta")
        assert "<li>alpha</li>" in html
        assert "<li>beta</li>" in html

    def test_blockquote(self):
        html = markdown_to_html("> wise words here")
        assert "<blockquote>wise words here</blockquote>" in html

    def test_link(self):
        html = markdown_to_html("[click](https://example.com)")
        assert '<a href="https://example.com"' in html
        assert "click" in html

    def test_fenced_code_block(self):
        html = markdown_to_html("```python\nx = 1\n```")
        assert "<pre><code>" in html
        assert "x = 1" in html
        assert "</code></pre>" in html

    def test_fenced_code_block_escapes_html(self):
        html = markdown_to_html("```\n<div>alert</div>\n```")
        assert "&lt;div&gt;" in html
        assert "<div>" not in html.replace("&lt;div&gt;", "")

    def test_heading_with_inline_formatting(self):
        html = markdown_to_html("## **Bold** section")
        assert "<h2>" in html
        assert "<strong>Bold</strong>" in html

    def test_consecutive_lines_same_paragraph(self):
        html = markdown_to_html("line one\nline two")
        assert "line one line two" in html
        assert "<p>" in html

    def test_blank_line_separates_paragraphs(self):
        html = markdown_to_html("para one\n\npara two")
        assert "<p>para one</p>" in html
        assert "<p>para two</p>" in html

    def test_heading_breaks_paragraph(self):
        html = markdown_to_html("text before\n# Heading\ntext after")
        assert "<p>text before</p>" in html
        assert "<h1>Heading</h1>" in html
        assert "<p>text after</p>" in html

    def test_list_breaks_paragraph(self):
        html = markdown_to_html("text\n- item")
        assert "<p>text</p>" in html
        assert "<li>item</li>" in html


# --- XSS / security ---------------------------------------------------------


class TestXssPrevention:
    def test_script_tag_escaped(self):
        html = markdown_to_html('<script>alert("xss")</script>')
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_raw_html_escaped(self):
        html = markdown_to_html("<b>bold</b>")
        assert "<b>" not in html
        assert "&lt;b&gt;" in html

    def test_img_tag_escaped(self):
        html = markdown_to_html('<img src=x onerror=alert(1)>')
        assert "<img" not in html
        assert "&lt;img" in html

    def test_div_injection_escaped(self):
        html = markdown_to_html('<div onclick="alert(1)">click</div>')
        assert "<div" not in html

    def test_javascript_link(self):
        html = markdown_to_html("[click](javascript:alert(1))")
        assert 'href="javascript:' not in html
        assert "(javascript:alert(1))" in html

    def test_data_link(self):
        html = markdown_to_html("[click](data:text/html,<script>)")
        assert 'href="data:' not in html

    def test_vbscript_link(self):
        html = markdown_to_html("[click](vbscript:MsgBox)")
        assert 'href="vbscript:' not in html

    def test_file_link(self):
        html = markdown_to_html("[click](file:///etc/passwd)")
        assert 'href="file:' not in html

    def test_html_entity_injection(self):
        html = markdown_to_html("&lt;script&gt;alert(1)&lt;/script&gt;")
        assert "<script>" not in html

    def test_nested_markdown_with_html(self):
        html = markdown_to_html("**<script>evil</script>**")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


# --- sanitize_html ----------------------------------------------------------


class TestSanitizeHtml:
    def test_strips_script_tags(self):
        html = sanitize_html("<p>text</p><script>alert(1)</script><p>more</p>")
        assert "<script>" not in html
        assert "<p>text</p>" in html
        assert "<p>more</p>" in html

    def test_strips_onclick(self):
        html = sanitize_html('<a href="https://example.com" onclick="alert(1)">link</a>')
        assert "onclick" not in html
        assert "alert" not in html

    def test_strips_onerror(self):
        html = sanitize_html('<img src="https://example.com/img.png" onerror="alert(1)">')
        assert "onerror" not in html

    def test_strips_style_expressions(self):
        html = sanitize_html('<div style="background: expression(alert(1))">x</div>')
        assert "expression" not in html

    def test_allows_safe_tags(self):
        html = sanitize_html("<h1>Title</h1><p>text</p><strong>bold</strong>")
        assert "<h1>" in html
        assert "<p>" in html
        assert "<strong>" in html

    def test_allows_links(self):
        html = sanitize_html('<a href="https://example.com" target="_blank">link</a>')
        assert 'href="https://example.com"' in html
        assert 'target="_blank"' in html

    def test_strips_dangerous_href(self):
        html = sanitize_html('<a href="javascript:alert(1)">link</a>')
        assert "javascript:" not in html

    def test_strips_unknown_tags(self):
        html = sanitize_html("<custom-tag>content</custom-tag>")
        assert "<custom-tag>" not in html
        assert "content" in html

    def test_strips_html_comments(self):
        html = sanitize_html("<!-- comment --><p>text</p><!-- another -->")
        assert "<!--" not in html
        assert "<p>text</p>" in html

    def test_strips_unknown_attributes(self):
        html = sanitize_html('<p data-x="y">text</p>')
        assert "data-x" not in html
        assert "<p>" in html

    def test_empty(self):
        assert sanitize_html("") == ""

    def test_preserves_blockquote(self):
        html = sanitize_html("<blockquote>wise words</blockquote>")
        assert "<blockquote>" in html

    def test_preserves_code_block(self):
        html = sanitize_html("<pre><code>x = 1</code></pre>")
        assert "<pre><code>" in html

    def test_strips_iframe(self):
        html = sanitize_html('<iframe src="https://evil.com"></iframe>')
        assert "<iframe" not in html

    def test_strips_script_with_attributes(self):
        html = sanitize_html('<script src="https://evil.com/steal.js"></script>')
        assert "<script" not in html


# --- build_post_html --------------------------------------------------------


class TestBuildPostHtml:
    def test_basic_article(self):
        html = build_post_html("My Title", "Some **bold** content.")
        assert "<h1>My Title</h1>" in html
        assert "<strong>bold</strong>" in html
        assert "Some bold content." in html or "Some <strong>bold</strong> content." in html

    def test_empty_title(self):
        html = build_post_html("", "Body text.")
        assert "<h1>" not in html
        assert "Body text." in html

    def test_empty_body(self):
        html = build_post_html("Title", "")
        assert "<h1>Title</h1>" in html
        assert "<p>" not in html

    def test_both_empty(self):
        html = build_post_html("", "")
        assert html == ""

    def test_with_images(self):
        images = [
            ImageRef(url="https://example.com/img1.jpg", alt="Image 1", caption="Caption 1"),
            ImageRef(url="https://example.com/img2.png", alt="Image 2"),
        ]
        html = build_post_html("Title", "Body.", images=images)
        assert '<img src="https://example.com/img1.jpg"' in html
        assert 'alt="Image 1"' in html
        assert "Caption 1" in html
        assert '<img src="https://example.com/img2.png"' in html

    def test_image_dangerous_url_skipped(self):
        images = [ImageRef(url="javascript:alert(1)", alt="evil")]
        html = build_post_html("Title", "Body.", images=images)
        assert "javascript:" not in html
        assert "<img" not in html

    def test_with_sources(self):
        sources = [
            SourceRef(title="Source One", url="https://example.com", provider="web"),
            SourceRef(title="Source Two", url="https://other.com"),
        ]
        html = build_post_html("Title", "Body.", sources=sources)
        assert "<h2>Sources</h2>" in html
        assert "<li>" in html
        assert "Source One" in html
        assert "Source Two" in html
        assert 'href="https://example.com"' in html

    def test_sources_dangerous_url(self):
        sources = [SourceRef(title="Evil", url="javascript:alert(1)")]
        html = build_post_html("Title", "Body.", sources=sources)
        assert "javascript:" not in html
        assert "Evil" in html

    def test_no_images_no_sources(self):
        html = build_post_html("Title", "Body.")
        assert "<h1>Title</h1>" in html
        assert "<p>Body.</p>" in html
        assert "<h2>Sources</h2>" not in html
        assert "<img" not in html

    def test_representative_article(self):
        """Test a realistic article with headings, lists, links, and images."""
        body = """## Introduction

This is a **comprehensive guide** about solar panels.

### How They Work

Solar panels convert *sunlight* into electricity using photovoltaic cells.

Key benefits:

- Renewable energy source
- Low maintenance costs
- Reduces electricity bills

> Solar energy is the future of power generation.

For more info, visit [Energy.gov](https://www.energy.gov) or [learn more](https://example.com/solar)."""
        images = [
            ImageRef(
                url="https://upload.wikimedia.org/solar.jpg",
                alt="Solar panel field",
                caption="A solar panel installation",
                attribution="Photo by John Doe / CC BY 4.0",
            )
        ]
        sources = [
            SourceRef(title="Department of Energy", url="https://www.energy.gov"),
            SourceRef(title="Solar Energy Guide", url="https://example.com/solar"),
        ]
        html = build_post_html("Solar Panels Guide", body, images=images, sources=sources)

        # Structure
        assert "<h1>Solar Panels Guide</h1>" in html
        assert "<h2>Introduction</h2>" in html
        assert "<h3>How They Work</h3>" in html

        # Inline formatting
        assert "<strong>comprehensive guide</strong>" in html
        assert "<em>sunlight</em>" in html

        # Lists
        assert "<ul>" in html
        assert "<li>Renewable energy source</li>" in html

        # Blockquote
        assert "<blockquote>" in html
        assert "Solar energy is the future" in html

        # Links
        assert 'href="https://www.energy.gov"' in html
        assert 'href="https://example.com/solar"' in html

        # Images
        assert '<img src="https://upload.wikimedia.org/solar.jpg"' in html
        assert "solar panel installation" in html  # caption (may be in <em>)
        assert "Photo by John Doe" in html

        # Sources
        assert "<h2>Sources</h2>" in html
        assert "Department of Energy" in html

    def test_deterministic_output(self):
        """Same input always produces same output."""
        body = "## Section\n\n**Bold** and *italic*."
        out1 = build_post_html("Title", body)
        out2 = build_post_html("Title", body)
        assert out1 == out2


# --- Integration: markdown_to_html + sanitize_html --------------------------


class TestIntegration:
    def test_full_pipeline(self):
        """Convert markdown, build post, sanitize — no dangerous output."""
        body = "## Intro\n\nText with [link](https://example.com).\n\n- item"
        html = build_post_html("Test", body)
        clean = sanitize_html(html)
        assert "<h2>Intro</h2>" in clean
        assert 'href="https://example.com"' in clean
        assert "<li>item</li>" in clean
        assert "<script>" not in clean

    def test_xss_through_full_pipeline(self):
        """XSS payload through full build + sanitize is neutralized."""
        body = '<script>alert("xss")</script>\n\n[click](javascript:alert(1))'
        html = build_post_html("Test", body)
        clean = sanitize_html(html)
        assert "<script>" not in clean
        # javascript: appears as plain text (safe), not as an executable link
        assert 'href="javascript:' not in clean
        assert "onclick" not in clean

    def test_empty_content_full_pipeline(self):
        html = build_post_html("", "")
        clean = sanitize_html(html)
        assert clean == ""
