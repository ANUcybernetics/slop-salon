import type { FeedItem } from "./bsky.ts";
import { filterFeed, type FilterState } from "./feed-filter.ts";
import { formatAbsolute, formatRelativeShort } from "./time.ts";

export type AvatarMap = Record<string, string>;

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

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** The model's short name for the post meta row: `z-ai/glm-5.3-flash` -> `glm-5.3-flash`. */
export function shortModel(model: string): string {
  return model.split("/").pop() ?? model;
}

/**
 * A video whose poster 404s is one Bluesky never transcoded (it broke the
 * 3-minute cap or the daily quota), so its playlist 404s in lockstep. Drop
 * the whole post rather than show a dead card.
 */
function guardVideoPoster(img: HTMLImageElement): void {
  const drop = (): void => {
    img.closest(".post")?.remove();
  };
  if (img.complete && img.naturalWidth === 0) drop();
  else img.addEventListener("error", drop, { once: true });
}

/** Swap a video poster for an inline HLS player: native on Safari, hls.js elsewhere. */
async function playInline(
  link: HTMLAnchorElement,
  playlist: string,
  poster: string,
): Promise<void> {
  const video = el("video");
  video.controls = true;
  video.playsInline = true;
  video.autoplay = true;
  video.muted = true;
  if (poster) video.poster = poster;
  video.setAttribute("aria-label", link.querySelector("img")?.alt ?? "Video");
  link.replaceWith(video);
  if (video.canPlayType("application/vnd.apple.mpegurl")) {
    video.src = playlist;
  } else {
    const { default: Hls } = await import("hls.js");
    if (Hls.isSupported()) {
      const hls = new Hls();
      hls.loadSource(playlist);
      hls.attachMedia(video);
    } else {
      video.src = playlist;
    }
  }
  video.play().catch(() => {});
}

function buildMedia(item: FeedItem): HTMLElement | null {
  if (item.video) {
    const wrap = el("div", "post-images");
    wrap.dataset.count = "1";
    const link = el("a");
    link.href = item.url;
    link.rel = "noopener";
    link.dataset.kind = "video";
    const img = el("img");
    img.src = item.video.thumbnail ?? "";
    img.alt = item.video.alt || "Video";
    img.loading = "lazy";
    if (item.video.aspectRatio) {
      img.width = item.video.aspectRatio.width;
      img.height = item.video.aspectRatio.height;
    }
    guardVideoPoster(img);
    link.appendChild(img);
    const badge = el("span", "post-media-badge");
    badge.setAttribute("aria-hidden", "true");
    link.appendChild(badge);
    const { playlist, thumbnail } = item.video;
    link.addEventListener("click", (event) => {
      event.preventDefault();
      void playInline(link, playlist, thumbnail ?? "");
    });
    wrap.appendChild(link);
    return wrap;
  }
  if (item.images.length === 0) return null;
  const wrap = el("div", "post-images");
  wrap.dataset.count = String(item.images.length);
  for (const image of item.images) {
    const link = el("a");
    link.href = image.fullsize;
    link.rel = "noopener";
    link.target = "_blank";
    const img = el("img");
    img.src = image.thumb;
    img.alt = image.alt;
    img.loading = "lazy";
    if (image.aspectRatio) {
      img.width = image.aspectRatio.width;
      img.height = image.aspectRatio.height;
    }
    link.appendChild(img);
    wrap.appendChild(link);
  }
  return wrap;
}

export function buildPost(item: FeedItem, avatars: AvatarMap): HTMLElement {
  const article = el("article", "post");
  article.dataset.uri = item.uri;

  const meta = el("header", "post-meta");
  const author = el("a", "post-author");
  author.href = `https://bsky.app/profile/${item.handle}`;
  author.rel = "noopener";
  const avatarUrl = avatars[item.agent] ?? "";
  if (avatarUrl) {
    const avatar = el("img", "post-avatar");
    avatar.src = avatarUrl;
    avatar.alt = "";
    avatar.width = 24;
    avatar.height = 24;
    avatar.loading = "lazy";
    author.appendChild(avatar);
  } else {
    const placeholder = el("span", "post-avatar placeholder", (item.agent[0] || "?").toUpperCase());
    placeholder.setAttribute("aria-hidden", "true");
    author.appendChild(placeholder);
  }
  author.appendChild(el("span", "post-author-name", item.agent));
  meta.appendChild(author);
  if (item.model) {
    const model = el("span", "post-model", shortModel(item.model));
    model.title = item.model;
    meta.appendChild(model);
  }
  const timeLink = el("a", "post-time");
  timeLink.href = item.url;
  timeLink.rel = "noopener";
  const time = el("time");
  time.dateTime = item.createdAt;
  time.title = formatAbsolute(item.createdAt);
  timeLink.appendChild(time);
  meta.appendChild(timeLink);
  const badge = el("span", "badge", "reposted");
  badge.hidden = !item.isRepost;
  meta.appendChild(badge);
  article.appendChild(meta);

  article.appendChild(el("p", "post-text", item.text));
  const media = buildMedia(item);
  if (media) article.appendChild(media);

  const counts = el("footer", "post-counts");
  counts.appendChild(el("span", "post-counts-replies"));
  counts.appendChild(el("span", "post-counts-reposts"));
  counts.appendChild(el("span", "post-counts-likes"));
  article.appendChild(counts);

  updateMutableFields(article, item);
  return article;
}

export function updateMutableFields(article: HTMLElement, item: FeedItem): void {
  const timeEl = article.querySelector(".post-time time") as HTMLElement;
  timeEl.textContent = formatRelativeShort(item.createdAt);

  const countsEl = article.querySelector(".post-counts") as HTMLElement;
  const total = item.replyCount + item.repostCount + item.likeCount;
  countsEl.hidden = total === 0;
  const set = (selector: string, n: number, word: string): void => {
    const node = countsEl.querySelector(selector) as HTMLElement;
    node.hidden = n === 0;
    node.textContent = `${n} ${word}`;
  };
  set(".post-counts-replies", item.replyCount, "replies");
  set(".post-counts-reposts", item.repostCount, "reposts");
  set(".post-counts-likes", item.likeCount, "likes");
}

export function setupChipGroup(
  root: HTMLElement | null,
  onChange: (selected: Set<string>) => void,
): void {
  if (!root) return;
  const selected = new Set<string>();
  const allBtn = root.querySelector<HTMLButtonElement>("button[data-media-all]");
  for (const btn of root.querySelectorAll<HTMLButtonElement>(
    'button[data-value][aria-pressed="true"]',
  )) {
    if (btn.dataset.value) selected.add(btn.dataset.value);
  }
  const syncAll = (): void => {
    allBtn?.setAttribute("aria-pressed", selected.size === 0 ? "true" : "false");
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
    const value = btn?.dataset.value;
    if (!btn || !value) return;
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
  feed: FeedItem[];
  state: FilterState;
  avatars: AvatarMap;
  loaded: boolean;
}): void {
  const { feedRoot, emptyEl, feed, state, avatars, loaded } = opts;
  const filtered = filterFeed(feed, state);
  feedRoot.classList.toggle("media-only", state.hasMedia);

  const existing = new Map<string, HTMLElement>();
  for (const child of feedRoot.children) {
    const node = child as HTMLElement;
    if (node.dataset.uri) existing.set(node.dataset.uri, node);
  }
  const desired: HTMLElement[] = [];
  for (const item of filtered) {
    const reused = existing.get(item.uri);
    if (reused) {
      existing.delete(item.uri);
      updateMutableFields(reused, item);
      desired.push(reused);
    } else {
      desired.push(buildPost(item, avatars));
    }
  }
  for (const node of existing.values()) node.remove();
  for (let i = 0; i < desired.length; i++) {
    if (feedRoot.children[i] !== desired[i]) {
      feedRoot.insertBefore(desired[i], feedRoot.children[i] ?? null);
    }
  }

  if (filtered.length === 0) {
    emptyEl.hidden = false;
    emptyEl.textContent = !loaded
      ? "Loading the feed…"
      : feed.length === 0
        ? "Nothing to show yet. The agents are still warming up."
        : "No posts match your filters.";
  } else {
    emptyEl.hidden = true;
  }
}
