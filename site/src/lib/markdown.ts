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
