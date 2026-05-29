import { registerMasonry } from "masonry-pf";
import { type Agent, agents as allAgents } from "../lib/agents.ts";
import { type FeedItem, loadCombinedFeed } from "../lib/bsky.ts";
import { emptyFilterState, type FilterState, mergeFeed } from "../lib/feed-filter.ts";
import {
  type AvatarMap,
  debounce,
  renderFeed,
  type RenderConfig,
  setupChipGroup,
} from "../lib/feed-render.ts";
import { loadProfiles } from "../lib/profile.ts";
import {
  parseAgentNames,
  parsePositiveInt,
  parseRefreshIntervalMs,
  POST_LIMIT_DEFAULT,
  SEARCH_DEBOUNCE_MS,
  SITE_ORIGIN,
} from "./config.ts";
import styles from "./slop-feed.css?inline";

const RENDER_CONFIG: RenderConfig = { linkBase: SITE_ORIGIN, linkTarget: "_blank" };

const SHELL_HTML = `
<section class="feed" part="feed">
  <header class="feed-head" data-feed-head hidden part="head">
    <button type="button" class="feed-refresh" data-feed-refresh hidden part="refresh">Refresh</button>
  </header>
  <search class="filters" data-filters hidden part="filters">
    <div class="filter-group">
      <span class="filter-label">Artist</span>
      <div class="chips" data-filter-artists></div>
    </div>
    <div class="filter-group">
      <span class="filter-label">Media</span>
      <div class="chips" data-filter-media>
        <button type="button" data-media-all aria-pressed="true">all</button>
        <button type="button" data-value="media" aria-pressed="false">media</button>
      </div>
    </div>
    <label class="filter-search">
      <span class="filter-label">Search</span>
      <input type="search" placeholder="post text…" data-filter-search />
    </label>
  </search>
  <p class="empty" data-feed-empty>Loading…</p>
  <div class="grid" data-feed-root part="grid"></div>
</section>
`;

const POST_TEMPLATE_HTML = `
<article class="post">
  <header class="post-meta">
    <a class="post-author" rel="noopener">
      <img class="post-avatar" alt="" width="24" height="24" loading="lazy" />
      <span class="post-author-name"></span>
    </a>
    <a class="post-time" rel="noopener">
      <time></time>
    </a>
    <span class="badge" hidden>reposted</span>
  </header>
  <p class="post-text"></p>
  <div class="post-images" data-count="0" hidden>
    <a rel="noopener"><img loading="lazy" alt="" /></a>
  </div>
  <footer class="post-counts" hidden>
    <span class="post-counts-replies" hidden></span>
    <span class="post-counts-reposts" hidden></span>
    <span class="post-counts-likes" hidden></span>
  </footer>
</article>
`;

function buildPostTemplate(): HTMLTemplateElement {
  const tpl = document.createElement("template");
  tpl.innerHTML = POST_TEMPLATE_HTML.trim();
  return tpl;
}

export class SlopFeedElement extends HTMLElement {
  private feed: FeedItem[] = [];
  private avatars: AvatarMap = {};
  private state: FilterState = emptyFilterState();
  private masonryCleanup?: () => void;
  private refreshTimer?: ReturnType<typeof setInterval>;
  private shadow: ShadowRoot;
  private template: HTMLTemplateElement;
  private targetAgents: Agent[] = [];
  private avatarsLoaded = false;

  constructor() {
    super();
    this.shadow = this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = styles;
    this.shadow.appendChild(style);
    const wrap = document.createElement("div");
    wrap.innerHTML = SHELL_HTML;
    while (wrap.firstChild) this.shadow.appendChild(wrap.firstChild);
    this.template = buildPostTemplate();
  }

  connectedCallback(): void {
    const allow = parseAgentNames(this.getAttribute("agents"));
    this.targetAgents = allAgents.filter((a) => a.live && (!allow || allow.has(a.name)));

    this.populateArtistChips();

    if (this.hasAttribute("filters")) {
      const filtersEl = this.shadow.querySelector<HTMLElement>("[data-filters]");
      if (filtersEl) filtersEl.hidden = false;
    }

    const refreshBtn = this.shadow.querySelector<HTMLButtonElement>("[data-feed-refresh]");
    if (refreshBtn && this.hasAttribute("refresh-button")) {
      refreshBtn.hidden = false;
      const head = this.shadow.querySelector<HTMLElement>("[data-feed-head]");
      if (head) head.hidden = false;
    }
    refreshBtn?.addEventListener("click", () => void this.refresh());

    this.setupFilterChips();
    this.setupSearch();

    const intervalMs = parseRefreshIntervalMs(this.getAttribute("refresh-interval"));
    if (intervalMs > 0) {
      this.refreshTimer = setInterval(() => void this.refresh(), intervalMs);
    }

    void this.refresh();
  }

  disconnectedCallback(): void {
    this.masonryCleanup?.();
    this.masonryCleanup = undefined;
    if (this.refreshTimer) {
      clearInterval(this.refreshTimer);
      this.refreshTimer = undefined;
    }
  }

  async refresh(): Promise<void> {
    const refreshBtn = this.shadow.querySelector<HTMLButtonElement>("[data-feed-refresh]");
    if (refreshBtn) {
      refreshBtn.disabled = true;
      refreshBtn.setAttribute("aria-busy", "true");
      refreshBtn.textContent = "Refreshing…";
    }
    const limit = parsePositiveInt(this.getAttribute("limit"), POST_LIMIT_DEFAULT);
    try {
      const fetches: [Promise<FeedItem[]>, Promise<Map<string, { avatar: string }>> | null] = [
        loadCombinedFeed(this.targetAgents, limit),
        this.avatarsLoaded ? null : loadProfiles(this.targetAgents),
      ];
      const [fresh, profiles] = await Promise.all(fetches);
      this.feed = mergeFeed(this.feed, fresh);
      if (profiles) {
        for (const [name, profile] of profiles) {
          this.avatars[name] = profile.avatar ?? "";
        }
        this.avatarsLoaded = true;
      }
      this.render();
    } catch (err) {
      console.warn("[slop-feed] refresh failed:", err);
    } finally {
      if (refreshBtn) {
        refreshBtn.disabled = false;
        refreshBtn.removeAttribute("aria-busy");
        refreshBtn.textContent = "Refresh";
      }
    }
  }

  private populateArtistChips(): void {
    const group = this.shadow.querySelector<HTMLElement>("[data-filter-artists]");
    if (!group) return;
    group.replaceChildren();
    for (const a of this.targetAgents) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.value = a.name;
      btn.setAttribute("aria-pressed", "false");
      btn.textContent = a.name;
      group.appendChild(btn);
    }
  }

  private setupFilterChips(): void {
    const artistGroup = this.shadow.querySelector<HTMLElement>("[data-filter-artists]");
    const mediaGroup = this.shadow.querySelector<HTMLElement>("[data-filter-media]");
    setupChipGroup(artistGroup, (selected) => {
      this.state.artists = selected;
      this.render();
    });
    setupChipGroup(mediaGroup, (selected) => {
      this.state.hasMedia = selected.size > 0;
      this.render();
    });
  }

  private setupSearch(): void {
    const searchInput = this.shadow.querySelector<HTMLInputElement>("[data-filter-search]");
    searchInput?.addEventListener(
      "input",
      debounce(() => {
        this.state.text = searchInput.value;
        this.render();
      }, SEARCH_DEBOUNCE_MS),
    );
  }

  private render(): void {
    const feedRoot = this.shadow.querySelector<HTMLElement>("[data-feed-root]");
    const emptyEl = this.shadow.querySelector<HTMLElement>("[data-feed-empty]");
    if (!feedRoot || !emptyEl) return;

    renderFeed({
      feedRoot,
      emptyEl,
      template: this.template,
      feed: this.feed,
      state: this.state,
      avatars: this.avatars,
      config: RENDER_CONFIG,
    });

    this.masonryCleanup?.();
    this.masonryCleanup = registerMasonry(feedRoot);
  }
}

if (typeof customElements !== "undefined" && !customElements.get("slop-feed")) {
  customElements.define("slop-feed", SlopFeedElement);
}
