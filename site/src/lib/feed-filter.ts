import type { FeedItem } from "./bsky.ts";

export type FilterState = {
  artists: Set<string>;
  hasMedia: boolean;
  text: string;
};

export function emptyFilterState(): FilterState {
  return { artists: new Set(), hasMedia: false, text: "" };
}

export function mergeFeed(initial: FeedItem[], fresh: FeedItem[]): FeedItem[] {
  const byUri = new Map<string, FeedItem>();
  for (const item of initial) byUri.set(item.uri, item);
  for (const item of fresh) byUri.set(item.uri, item);
  return [...byUri.values()].toSorted((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
}

export function filterFeed(items: FeedItem[], state: FilterState): FeedItem[] {
  const needle = state.text.trim().toLowerCase();
  return items.filter((item) => {
    if (state.artists.size > 0 && !state.artists.has(item.agent)) return false;
    if (state.hasMedia && item.mediaTypes.length === 0) return false;
    if (needle && !item.text.toLowerCase().includes(needle)) return false;
    return true;
  });
}
