import { registerMasonry } from "masonry-pf";
import { agents, liveAgents } from "./agents.ts";
import { type FeedItem, loadCombinedFeed, loadProfiles } from "./bsky.ts";
import { emptyFilterState, type FilterState, mergeFeed } from "./feed-filter.ts";
import { type AvatarMap, debounce, renderFeed, setupChipGroup } from "./feed-render.ts";

const POST_LIMIT_PER_AGENT = 20;
const SEARCH_DEBOUNCE_MS = 150;

/** Fill each artist card's avatar and bio from its live Bluesky profile. */
async function fillArtistCards(): Promise<AvatarMap> {
  const profiles = await loadProfiles(liveAgents());
  const avatars: AvatarMap = {};
  for (const [name, profile] of profiles) {
    avatars[name] = profile.avatar;
    const card = document.querySelector<HTMLElement>(`[data-artist="${name}"]`);
    if (!card) continue;
    const blurb = card.querySelector<HTMLElement>("[data-artist-blurb]");
    if (blurb && profile.description) {
      blurb.textContent = profile.description;
      blurb.classList.remove("muted");
    }
    const slot = card.querySelector<HTMLElement>("[data-artist-avatar]");
    if (slot && profile.avatar) {
      const img = document.createElement("img");
      img.className = "artist-avatar";
      img.src = profile.avatar;
      img.alt = "";
      img.width = 56;
      img.height = 56;
      slot.replaceWith(img);
    }
  }
  return avatars;
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
  if (!feedRoot || !emptyEl) return;

  let feed: FeedItem[] = [];
  let avatars: AvatarMap = {};
  let loaded = false;
  const state: FilterState = emptyFilterState();
  state.hasMedia = true; // the "media" chip ships pre-pressed
  let masonryCleanup: (() => void) | undefined;

  const update = (): void => {
    renderFeed({ feedRoot, emptyEl, feed, state, avatars, loaded });
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
      loaded = true;
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

  update();
  void fillArtistCards().then((map) => {
    avatars = map;
    update();
  });
  void refresh();
}
