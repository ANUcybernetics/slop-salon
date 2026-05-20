import MarkdownIt from "markdown-it";

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: false,
  typographer: true,
});

export function renderMarkdown(source: string): string {
  return md.render(source);
}

export function firstParagraph(source: string): string {
  for (const block of source.split(/\n{2,}/)) {
    const trimmed = block.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    return trimmed.replace(/\s+/g, " ");
  }
  return "";
}
