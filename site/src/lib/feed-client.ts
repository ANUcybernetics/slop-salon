import { agents } from "./agents.ts";
import { loadCombinedFeed, type FeedItem } from "./bsky.ts";
import {
  emptyFilterState,
  filterFeed,
  mergeFeed,
  type FilterState,
  type MediaFilter,
} from "./feed-filter.ts";

const POST_LIMIT_PER_AGENT = 20;
const SEARCH_DEBOUNCE_MS = 150;

const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

function relativeTime(iso: string): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const seconds = Math.round((then - Date.now()) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 60) return rtf.format(seconds, "second");
  if (abs < 3600) return rtf.format(Math.round(seconds / 60), "minute");
  if (abs < 86_400) return rtf.format(Math.round(seconds / 3600), "hour");
  return rtf.format(Math.round(seconds / 86_400), "day");
}

function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderPost(item: FeedItem): string {
  const imagesHtml =
    item.images.length === 0
      ? ""
      : `<div class="post-images" data-count="${item.images.length}">${item.images
          .map((img) => {
            const dims = img.aspectRatio
              ? ` width="${img.aspectRatio.width}" height="${img.aspectRatio.height}"`
              : "";
            return `<a href="${esc(img.fullsize)}" rel="noopener"><img src="${esc(img.thumb)}" alt="${esc(img.alt)}" loading="lazy"${dims}></a>`;
          })
          .join("")}</div>`;
  const counts = item.replyCount + item.repostCount + item.likeCount;
  const countsHtml =
    counts === 0
      ? ""
      : `<footer class="post-counts">${
          item.replyCount > 0 ? `<span>${item.replyCount} replies</span>` : ""
        }${
          item.repostCount > 0 ? `<span>${item.repostCount} reposts</span>` : ""
        }${item.likeCount > 0 ? `<span>${item.likeCount} likes</span>` : ""}</footer>`;
  const repostBadge = item.isRepost ? `<span class="badge">reposted</span>` : "";
  return `<article class="post"><header class="post-meta"><a class="post-author" href="https://bsky.app/profile/${esc(item.handle)}" rel="noopener">@${esc(item.handle)}</a>${repostBadge}<a class="post-time" href="${esc(item.url)}" rel="noopener"><time datetime="${esc(item.createdAt)}">${esc(relativeTime(item.createdAt))}</time></a></header><p class="post-text">${esc(item.text)}</p>${imagesHtml}${countsHtml}</article>`;
}

function render(
  feed: FeedItem[],
  state: FilterState,
  feedRoot: HTMLElement,
  emptyEl: HTMLElement,
): void {
  const filtered = filterFeed(feed, state);
  if (filtered.length === 0) {
    feedRoot.innerHTML = "";
    emptyEl.hidden = false;
    emptyEl.textContent =
      feed.length === 0
        ? "Nothing to show yet. The agents are still warming up."
        : "No posts match your filters.";
    return;
  }
  emptyEl.hidden = true;
  feedRoot.innerHTML = filtered.map(renderPost).join("");
}

function debounce<A extends unknown[]>(
  fn: (...args: A) => void,
  ms: number,
): (...args: A) => void {
  let t: ReturnType<typeof setTimeout> | undefined;
  return (...args: A) => {
    if (t) clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

function readInitial(id: string): FeedItem[] {
  const el = document.getElementById(id);
  if (!el?.textContent) return [];
  try {
    return JSON.parse(el.textContent) as FeedItem[];
  } catch {
    return [];
  }
}

function setupChipGroup(
  root: HTMLElement | null,
  onChange: (selected: Set<string>) => void,
): void {
  if (!root) return;
  const selected = new Set<string>();
  root.addEventListener("click", (event) => {
    const target = event.target as HTMLElement;
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
    onChange(selected);
  });
}

export function init(): void {
  const feedRoot = document.querySelector<HTMLElement>("[data-feed-root]");
  const emptyEl = document.querySelector<HTMLElement>("[data-feed-empty]");
  const filtersEl = document.querySelector<HTMLElement>("[data-filters]");
  const refreshedEl = document.querySelector<HTMLTimeElement>("[data-refreshed]");
  const artistGroup = document.querySelector<HTMLElement>("[data-filter-artists]");
  const mediaGroup = document.querySelector<HTMLElement>("[data-filter-media]");
  const searchInput = document.querySelector<HTMLInputElement>("[data-filter-search]");
  if (!feedRoot || !emptyEl) return;

  let feed: FeedItem[] = readInitial("initial-feed");
  const state: FilterState = emptyFilterState();
  const update = (): void => render(feed, state, feedRoot, emptyEl);

  if (filtersEl) filtersEl.hidden = false;

  setupChipGroup(artistGroup, (selected) => {
    state.artists = selected;
    update();
  });
  setupChipGroup(mediaGroup, (selected) => {
    state.mediaTypes = selected as Set<MediaFilter>;
    update();
  });
  searchInput?.addEventListener(
    "input",
    debounce(() => {
      state.text = searchInput.value;
      update();
    }, SEARCH_DEBOUNCE_MS),
  );

  void (async () => {
    try {
      const fresh = await loadCombinedFeed(agents, POST_LIMIT_PER_AGENT);
      feed = mergeFeed(feed, fresh);
      update();
      if (refreshedEl) {
        const now = new Date();
        refreshedEl.dateTime = now.toISOString();
        refreshedEl.textContent = now.toUTCString();
      }
    } catch (err) {
      console.warn("[feed] refresh failed:", err);
    }
  })();
}
