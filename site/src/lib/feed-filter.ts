import type { FeedItem, MediaType } from "./bsky.ts";

export type MediaFilter = MediaType;

export type FilterState = {
  artists: Set<string>;
  mediaTypes: Set<MediaFilter>;
  text: string;
};

export function emptyFilterState(): FilterState {
  return { artists: new Set(), mediaTypes: new Set(), text: "" };
}

export function mergeFeed(initial: FeedItem[], fresh: FeedItem[]): FeedItem[] {
  const byUri = new Map<string, FeedItem>();
  for (const item of initial) byUri.set(item.uri, item);
  for (const item of fresh) byUri.set(item.uri, item);
  return [...byUri.values()].toSorted(
    (a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt),
  );
}

function matchesMedia(item: FeedItem, wanted: Set<MediaFilter>): boolean {
  if (wanted.size === 0) return true;
  for (const t of item.mediaTypes) {
    if (wanted.has(t)) return true;
  }
  return false;
}

export function filterFeed(items: FeedItem[], state: FilterState): FeedItem[] {
  const needle = state.text.trim().toLowerCase();
  return items.filter((item) => {
    if (state.artists.size > 0 && !state.artists.has(item.agent)) return false;
    if (!matchesMedia(item, state.mediaTypes)) return false;
    if (needle && !item.text.toLowerCase().includes(needle)) return false;
    return true;
  });
}
