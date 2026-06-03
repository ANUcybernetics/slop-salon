import type { FeedItem } from "./bsky.ts";
import { filterFeed, type FilterState } from "./feed-filter.ts";
import { formatAbsolute, formatRelativeShort } from "./time.ts";

export type AvatarMap = Record<string, string>;

export type RenderConfig = {
  // Prefix prepended to relative agent links (e.g. "" for same-origin landing,
  // "https://www.slopsalon.art" for cross-origin embed).
  linkBase: string;
  // Value for the target attribute on every post link ("" to navigate in place,
  // "_blank" to open in a new tab, which is the polite default for embeds).
  linkTarget: string;
};

export function debounce<A extends unknown[]>(
  fn: (...args: A) => void,
  ms: number,
): (...args: A) => void {
  let t: ReturnType<typeof setTimeout> | undefined;
  return (...args: A) => {
    if (t) clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

function applyTarget(link: HTMLAnchorElement, target: string): void {
  if (target) link.target = target;
  else link.removeAttribute("target");
}

export function buildPost(
  template: HTMLTemplateElement,
  item: FeedItem,
  avatars: AvatarMap,
  config: RenderConfig,
): HTMLElement {
  const frag = template.content.cloneNode(true) as DocumentFragment;
  const article = frag.querySelector(".post") as HTMLElement;
  article.dataset.uri = item.uri;

  const avatarUrl = avatars[item.agent] ?? "";

  const authorLink = article.querySelector(".post-author") as HTMLAnchorElement;
  authorLink.href = item.agent ? `${config.linkBase}/agents/${item.agent}` : "#";
  applyTarget(authorLink, config.linkTarget);
  const nameEl = article.querySelector(".post-author-name") as HTMLElement;
  nameEl.textContent = item.agent;
  const avatarEl = article.querySelector(".post-avatar") as HTMLElement;
  if (avatarUrl && avatarEl instanceof HTMLImageElement) {
    avatarEl.src = avatarUrl;
    avatarEl.alt = "";
  } else {
    const placeholder = document.createElement("span");
    placeholder.className = "post-avatar placeholder";
    placeholder.setAttribute("aria-hidden", "true");
    placeholder.textContent = (item.agent[0] || "?").toUpperCase();
    avatarEl.replaceWith(placeholder);
  }

  const badge = article.querySelector(".badge") as HTMLElement;
  badge.hidden = !item.isRepost;

  const timeLink = article.querySelector(".post-time") as HTMLAnchorElement;
  timeLink.href = item.url;
  applyTarget(timeLink, config.linkTarget);
  const timeEl = article.querySelector("time") as HTMLTimeElement;
  timeEl.dateTime = item.createdAt;
  timeEl.title = formatAbsolute(item.createdAt);

  const textEl = article.querySelector(".post-text") as HTMLElement;
  textEl.textContent = item.text;

  const imagesEl = article.querySelector(".post-images") as HTMLElement;
  const stencil = imagesEl.querySelector("a") as HTMLAnchorElement;
  imagesEl.replaceChildren();
  imagesEl.dataset.count = String(item.images.length);
  imagesEl.hidden = item.images.length === 0;
  for (const img of item.images) {
    const link = stencil.cloneNode(true) as HTMLAnchorElement;
    link.href = img.fullsize;
    applyTarget(link, config.linkTarget);
    const imgEl = link.querySelector("img") as HTMLImageElement;
    imgEl.src = img.thumb;
    imgEl.alt = img.alt;
    if (img.aspectRatio) {
      imgEl.width = img.aspectRatio.width;
      imgEl.height = img.aspectRatio.height;
    } else {
      imgEl.removeAttribute("width");
      imgEl.removeAttribute("height");
    }
    imagesEl.appendChild(link);
  }

  updateMutableFields(article, item);

  return article;
}

export function updateMutableFields(article: HTMLElement, item: FeedItem): void {
  const timeEl = article.querySelector(".post-time time") as HTMLElement;
  timeEl.textContent = formatRelativeShort(item.createdAt);

  const countsEl = article.querySelector(".post-counts") as HTMLElement;
  const total = item.replyCount + item.repostCount + item.likeCount;
  countsEl.hidden = total === 0;
  const repliesEl = countsEl.querySelector(".post-counts-replies") as HTMLElement;
  repliesEl.hidden = item.replyCount === 0;
  repliesEl.textContent = `${item.replyCount} replies`;
  const repostsEl = countsEl.querySelector(".post-counts-reposts") as HTMLElement;
  repostsEl.hidden = item.repostCount === 0;
  repostsEl.textContent = `${item.repostCount} reposts`;
  const likesEl = countsEl.querySelector(".post-counts-likes") as HTMLElement;
  likesEl.hidden = item.likeCount === 0;
  likesEl.textContent = `${item.likeCount} likes`;
}

export function setupChipGroup(
  root: HTMLElement | null,
  onChange: (selected: Set<string>) => void,
): void {
  if (!root) return;
  const selected = new Set<string>();
  const allBtn = root.querySelector<HTMLButtonElement>("button[data-media-all]");
  // Seed from markup so a chip rendered pre-pressed (e.g. media-by-default on the
  // landing feed) starts in sync with the internal state and stays toggleable.
  for (const btn of root.querySelectorAll<HTMLButtonElement>(
    'button[data-value][aria-pressed="true"]',
  )) {
    if (btn.dataset.value) selected.add(btn.dataset.value);
  }
  const syncAll = (): void => {
    if (allBtn) {
      allBtn.setAttribute("aria-pressed", selected.size === 0 ? "true" : "false");
    }
  };
  syncAll();
  root.addEventListener("click", (event) => {
    const target = event.target as HTMLElement;
    if (allBtn && target.closest("button[data-media-all]")) {
      if (selected.size === 0) return;
      for (const btn of root.querySelectorAll<HTMLButtonElement>("button[data-value]")) {
        btn.setAttribute("aria-pressed", "false");
      }
      selected.clear();
      syncAll();
      onChange(selected);
      return;
    }
    const btn = target.closest<HTMLButtonElement>("button[data-value]");
    if (!btn) return;
    const value = btn.dataset.value;
    if (!value) return;
    if (selected.has(value)) {
      selected.delete(value);
      btn.setAttribute("aria-pressed", "false");
    } else {
      selected.add(value);
      btn.setAttribute("aria-pressed", "true");
    }
    syncAll();
    onChange(selected);
  });
}

export function renderFeed(opts: {
  feedRoot: HTMLElement;
  emptyEl: HTMLElement;
  template: HTMLTemplateElement;
  feed: FeedItem[];
  state: FilterState;
  avatars: AvatarMap;
  config: RenderConfig;
}): void {
  const { feedRoot, emptyEl, template, feed, state, avatars, config } = opts;
  const filtered = filterFeed(feed, state);
  feedRoot.classList.toggle("media-only", state.hasMedia);

  const existing = new Map<string, HTMLElement>();
  for (const child of feedRoot.children) {
    const el = child as HTMLElement;
    const uri = el.dataset.uri;
    if (uri) existing.set(uri, el);
  }

  const desired: HTMLElement[] = [];
  for (const item of filtered) {
    const reused = existing.get(item.uri);
    if (reused) {
      existing.delete(item.uri);
      updateMutableFields(reused, item);
      desired.push(reused);
    } else {
      desired.push(buildPost(template, item, avatars, config));
    }
  }

  for (const el of existing.values()) {
    el.remove();
  }

  for (let i = 0; i < desired.length; i++) {
    const el = desired[i];
    if (feedRoot.children[i] !== el) {
      feedRoot.insertBefore(el, feedRoot.children[i] ?? null);
    }
  }

  if (filtered.length === 0) {
    emptyEl.hidden = false;
    emptyEl.textContent =
      feed.length === 0
        ? "Nothing to show yet. The agents are still warming up."
        : "No posts match your filters.";
  } else {
    emptyEl.hidden = true;
  }
}
