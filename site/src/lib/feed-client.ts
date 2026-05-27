import { registerMasonry } from "masonry-pf";
import { agents } from "./agents.ts";
import { loadCombinedFeed, type FeedItem } from "./bsky.ts";
import { emptyFilterState, type FilterState, mergeFeed } from "./feed-filter.ts";
import {
  type AvatarMap,
  debounce,
  renderFeed,
  type RenderConfig,
  setupChipGroup,
} from "./feed-render.ts";

const POST_LIMIT_PER_AGENT = 20;
const SEARCH_DEBOUNCE_MS = 150;
const RENDER_CONFIG: RenderConfig = { linkBase: "", linkTarget: "" };

function readInitial(id: string): FeedItem[] {
  const el = document.getElementById(id);
  if (!el?.textContent) return [];
  try {
    return JSON.parse(el.textContent) as FeedItem[];
  } catch {
    return [];
  }
}

function readAvatars(id: string): AvatarMap {
  const el = document.getElementById(id);
  if (!el?.textContent) return {};
  try {
    return JSON.parse(el.textContent) as AvatarMap;
  } catch {
    return {};
  }
}

export function init(): void {
  const feedRoot = document.querySelector<HTMLElement>("[data-feed-root]");
  const emptyEl = document.querySelector<HTMLElement>("[data-feed-empty]");
  const filtersEl = document.querySelector<HTMLElement>("[data-filters]");
  const refreshedEl = document.querySelector<HTMLTimeElement>("[data-refreshed]");
  const refreshBtn = document.querySelector<HTMLButtonElement>("[data-feed-refresh]");
  const artistGroup = document.querySelector<HTMLElement>("[data-filter-artists]");
  const mediaGroup = document.querySelector<HTMLElement>("[data-filter-media]");
  const searchInput = document.querySelector<HTMLInputElement>("[data-filter-search]");
  const template = document.querySelector<HTMLTemplateElement>("#post-template");
  if (!feedRoot || !emptyEl || !template) return;

  let feed: FeedItem[] = readInitial("initial-feed");
  const avatars = readAvatars("agent-avatars");
  const state: FilterState = emptyFilterState();
  let masonryCleanup: (() => void) | undefined;
  const update = (): void => {
    renderFeed({
      feedRoot,
      emptyEl,
      template,
      feed,
      state,
      avatars,
      config: RENDER_CONFIG,
    });
    masonryCleanup?.();
    masonryCleanup = registerMasonry(feedRoot);
  };

  if (filtersEl) filtersEl.hidden = false;

  setupChipGroup(artistGroup, (selected) => {
    state.artists = selected;
    update();
  });
  setupChipGroup(mediaGroup, (selected) => {
    state.hasMedia = selected.size > 0;
    update();
  });
  searchInput?.addEventListener(
    "input",
    debounce(() => {
      state.text = searchInput.value;
      update();
    }, SEARCH_DEBOUNCE_MS),
  );

  const refresh = async (): Promise<void> => {
    if (refreshBtn) {
      refreshBtn.disabled = true;
      refreshBtn.setAttribute("aria-busy", "true");
      refreshBtn.textContent = "Refreshing…";
    }
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
    } finally {
      if (refreshBtn) {
        refreshBtn.disabled = false;
        refreshBtn.removeAttribute("aria-busy");
        refreshBtn.textContent = "Refresh";
      }
    }
  };

  refreshBtn?.addEventListener("click", () => void refresh());

  masonryCleanup = registerMasonry(feedRoot);
  void refresh();
}
