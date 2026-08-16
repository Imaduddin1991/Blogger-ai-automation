import { describe, expect, it } from "vitest";

import { renderMarkdown } from "@/lib/markdown";

describe("renderMarkdown", () => {
  it("renders headings, paragraphs, lists, and blockquotes", () => {
    const html = renderMarkdown("# Title\n\nSome text.\n\n- one\n- two\n\n> quote");
    expect(html).toContain("<h1>Title</h1>");
    expect(html).toContain("<p>Some text.</p>");
    expect(html).toContain("<ul>");
    expect(html).toContain("<li>one</li>");
    expect(html).toContain("<li>two</li>");
    expect(html).toContain("<blockquote>quote</blockquote>");
  });

  it("renders inline formatting", () => {
    const html = renderMarkdown("**bold** and *italic* and `code` and [link](https://example.com)");
    expect(html).toContain("<strong>bold</strong>");
    expect(html).toContain("<em>italic</em>");
    expect(html).toContain("<code>code</code>");
    expect(html).toContain('<a href="https://example.com"');
  });

  it("escapes raw HTML so injected markup is never executed", () => {
    const html = renderMarkdown('<script>alert("xss")</script> and <b>tag</b>');
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<b>tag</b>");
    expect(html).toContain("&lt;b&gt;tag&lt;/b&gt;");
  });

  it("neutralizes dangerous URL schemes in links", () => {
    const html = renderMarkdown(
      "[click](javascript:alert(1)) and [data](data:text/html;base64,PHNjcmlwdD4=) and [ok](https://example.com)",
    );
    expect(html).not.toContain('href="javascript:');
    expect(html).not.toContain('href="data:');
    expect(html).toContain("(javascript:alert(1))");
    expect(html).toContain('<a href="https://example.com"');
  });

  it("keeps fenced code blocks intact and escaped", () => {
    const html = renderMarkdown("```js\nconst x = 1 < 2;\n```");
    expect(html).toContain("<pre><code>");
    expect(html).toContain("const x = 1 &lt; 2;");
    expect(html).toContain("</code></pre>");
  });

  it("joins consecutive plain lines into one paragraph", () => {
    const html = renderMarkdown("first line\nsecond line");
    expect(html).toContain("<p>first line second line</p>");
  });
});
