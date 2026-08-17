export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Only http(s) URLs (and scheme-less relative/anchors) are ever allowed into
// href/src attributes. Anything else (javascript:, data:, vbscript:, file:)
// returns null so callers render plain text instead of an executable URL.
export function safeUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (/^(https?:\/\/)/i.test(trimmed)) return trimmed;
  if (!trimmed.includes(":")) return trimmed;
  return null;
}

function inlineMarkdown(value: string): string {
  return value
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_match, text: string, url: string) => {
      // Only http/https/mailto and scheme-less (relative/anchor) URLs become
      // links. Anything else (javascript:, data:, vbscript:, file:...) renders
      // as plain escaped text so a malicious markdown link can't execute in
      // the app origin when the article body is previewed.
      if (/^(https?:\/\/|mailto:)/i.test(url) || !url.includes(":")) {
        return `<a href="${url}" target="_blank" rel="noopener noreferrer">${text}</a>`;
      }
      return `${text} (${url})`;
    });
}

export function renderMarkdown(markdown: string): string {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const html: string[] = [];
  let para: string[] = [];
  let inList = false;
  let inCode = false;
  const flushPara = () => {
    if (para.length) {
      html.push(`<p>${inlineMarkdown(para.map(escapeHtml).join(" "))}</p>`);
      para = [];
    }
  };
  const closeList = () => {
    if (inList) {
      html.push("</ul>");
      inList = false;
    }
  };
  for (const raw of lines) {
    if (raw.trim().startsWith("```")) {
      flushPara();
      closeList();
      if (inCode) {
        html.push("</code></pre>");
        inCode = false;
      } else {
        html.push("<pre><code>");
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      html.push(escapeHtml(raw));
      continue;
    }
    const trimmed = raw.trim();
    if (trimmed === "") {
      flushPara();
      closeList();
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(trimmed);
    if (heading) {
      flushPara();
      closeList();
      const level = heading[1].length;
      html.push(`<h${level}>${inlineMarkdown(escapeHtml(heading[2]))}</h${level}>`);
      continue;
    }
    const listItem = /^[-*]\s+(.*)$/.exec(trimmed);
    if (listItem) {
      flushPara();
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${inlineMarkdown(escapeHtml(listItem[1]))}</li>`);
      continue;
    }
    if (trimmed.startsWith(">")) {
      flushPara();
      closeList();
      html.push(`<blockquote>${inlineMarkdown(escapeHtml(trimmed.replace(/^>\s?/, "")))}</blockquote>`);
      continue;
    }
    para.push(raw);
  }
  flushPara();
  closeList();
  if (inCode) {
    html.push("</code></pre>");
  }
  return html.join("\n");
}
