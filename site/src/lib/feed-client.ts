import { agents } from "./agents.ts";
import { loadCombinedFeed, type FeedItem } from "./bsky.ts";
import {
  emptyFilterState,
  filterFeed,
  mergeFeed,
  type FilterState,
  type MediaFilter,
} from "./feed-filter.ts";
import { formatAbsolute, formatRelative } from "./time.ts";

const POST_LIMIT_PER_AGENT = 20;
const SEARCH_DEBOUNCE_MS = 150;

function buildPost(
  postTpl: HTMLTemplateElement,
  item: FeedItem,
): DocumentFragment {
  const frag = postTpl.content.cloneNode(true) as DocumentFragment;
  const article = frag.querySelector(".post") as HTMLElement;

  const badge = article.querySelector(".badge") as HTMLElement;
  badge.hidden = !item.isRepost;

  const timeLink = article.querySelector(".post-time") as HTMLAnchorElement;
  timeLink.href = item.url;
  const timeEl = article.querySelector("time") as HTMLTimeElement;
  timeEl.dateTime = item.createdAt;
  const absEl = article.querySelector(".post-time-absolute") as HTMLElement;
  absEl.textContent = formatAbsolute(item.createdAt);
  const relEl = article.querySelector(".post-time-relative") as HTMLElement;
  relEl.textContent = formatRelative(item.createdAt);

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

  const countsEl = article.querySelector(".post-counts") as HTMLElement;
  const total = item.replyCount + item.repostCount + item.likeCount;
  countsEl.hidden = total === 0;
  const repliesEl = countsEl.querySelector(
    ".post-counts-replies",
  ) as HTMLElement;
  repliesEl.hidden = item.replyCount === 0;
  repliesEl.textContent = `${item.replyCount} replies`;
  const repostsEl = countsEl.querySelector(
    ".post-counts-reposts",
  ) as HTMLElement;
  repostsEl.hidden = item.repostCount === 0;
  repostsEl.textContent = `${item.repostCount} reposts`;
  const likesEl = countsEl.querySelector(".post-counts-likes") as HTMLElement;
  likesEl.hidden = item.likeCount === 0;
  likesEl.textContent = `${item.likeCount} likes`;

  return frag;
}

function groupByAgent(items: FeedItem[]): Map<string, FeedItem[]> {
  const byAgent = new Map<string, FeedItem[]>();
  for (const item of items) {
    let bucket = byAgent.get(item.agent);
    if (!bucket) {
      bucket = [];
      byAgent.set(item.agent, bucket);
    }
    bucket.push(item);
  }
  return byAgent;
}

function render(
  feed: FeedItem[],
  state: FilterState,
  feedRoot: HTMLElement,
  emptyEl: HTMLElement,
  postTpl: HTMLTemplateElement,
): void {
  const filtered = filterFeed(feed, state);
  const byAgent = groupByAgent(filtered);
  const cols = feedRoot.querySelectorAll<HTMLElement>("[data-agent-col]");

  let totalRendered = 0;
  for (const col of cols) {
    const name = col.dataset.agentCol ?? "";
    const items = byAgent.get(name) ?? [];
    const postsContainer = col.querySelector<HTMLElement>("[data-col-posts]");
    if (!postsContainer) continue;
    postsContainer.replaceChildren();
    for (const item of items) {
      postsContainer.appendChild(buildPost(postTpl, item));
    }
    col.hidden = items.length === 0;
    totalRendered += items.length;
  }

  if (totalRendered === 0) {
    emptyEl.hidden = false;
    emptyEl.textContent =
      feed.length === 0
        ? "Nothing to show yet. The agents are still warming up."
        : "No posts match your filters.";
  } else {
    emptyEl.hidden = true;
  }
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
  const postTpl = document.querySelector<HTMLTemplateElement>("#post-template");
  if (!feedRoot || !emptyEl || !postTpl) return;

  let feed: FeedItem[] = readInitial("initial-feed");
  const state: FilterState = emptyFilterState();
  const update = (): void => render(feed, state, feedRoot, emptyEl, postTpl);

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

  update();

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
