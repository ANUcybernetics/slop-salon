import { describe, expect, it } from "vitest";
import type { FeedItem, MediaType } from "./bsky.ts";
import { emptyFilterState, filterFeed, mergeFeed } from "./feed-filter.ts";

function item(overrides: Partial<FeedItem>): FeedItem {
  return {
    uri: "at://did:plc:lou/app.bsky.feed.post/1",
    agent: "lou",
    handle: "lou.example",
    text: "",
    createdAt: "2026-05-20T00:00:00.000Z",
    url: "https://bsky.app/profile/lou.example/post/1",
    isRepost: false,
    replyCount: 0,
    repostCount: 0,
    likeCount: 0,
    images: [],
    mediaTypes: [],
    ...overrides,
  };
}

describe("mergeFeed", () => {
  it("dedupes by uri, preferring fresh entries", () => {
    const stale = item({ uri: "x", text: "stale", likeCount: 1 });
    const fresh = item({ uri: "x", text: "fresh", likeCount: 9 });
    const result = mergeFeed([stale], [fresh]);
    expect(result).toHaveLength(1);
    expect(result[0]?.text).toBe("fresh");
    expect(result[0]?.likeCount).toBe(9);
  });

  it("sorts by createdAt descending", () => {
    const older = item({ uri: "a", createdAt: "2026-05-19T00:00:00Z" });
    const newer = item({ uri: "b", createdAt: "2026-05-20T00:00:00Z" });
    const newest = item({ uri: "c", createdAt: "2026-05-21T00:00:00Z" });
    const result = mergeFeed([older, newest], [newer]);
    expect(result.map((i) => i.uri)).toEqual(["c", "b", "a"]);
  });

  it("returns empty when both inputs are empty", () => {
    expect(mergeFeed([], [])).toEqual([]);
  });

  it("retains initial items not present in fresh", () => {
    const a = item({ uri: "a", text: "keep me" });
    const b = item({ uri: "b", text: "also keep" });
    const result = mergeFeed([a], [b]);
    expect(result).toHaveLength(2);
  });
});

describe("filterFeed", () => {
  const lou = item({ uri: "1", agent: "lou", text: "a sunset poem", mediaTypes: ["image"] });
  const mina = item({ uri: "2", agent: "mina", text: "a video essay", mediaTypes: ["video"] });
  const minaText = item({ uri: "3", agent: "mina", text: "just words here", mediaTypes: [] });
  const louAudio = item({ uri: "4", agent: "lou", text: "soundtrack drop", mediaTypes: ["audio"] });
  const all = [lou, mina, minaText, louAudio];

  it("returns everything with empty state", () => {
    expect(filterFeed(all, emptyFilterState())).toHaveLength(4);
  });

  it("filters by artist", () => {
    const state = emptyFilterState();
    state.artists = new Set(["lou"]);
    const result = filterFeed(all, state);
    expect(result.map((i) => i.uri)).toEqual(["1", "4"]);
  });

  it("treats multiple artists as union", () => {
    const state = emptyFilterState();
    state.artists = new Set(["lou", "mina"]);
    expect(filterFeed(all, state)).toHaveLength(4);
  });

  it("filters by media type", () => {
    const state = emptyFilterState();
    state.mediaTypes = new Set<MediaType>(["image"]);
    expect(filterFeed(all, state).map((i) => i.uri)).toEqual(["1"]);
  });

  it("drops posts with no media when a media type is selected", () => {
    const state = emptyFilterState();
    state.mediaTypes = new Set<MediaType>(["image"]);
    expect(filterFeed([minaText], state)).toEqual([]);
  });

  it("treats multiple media types as union", () => {
    const state = emptyFilterState();
    state.mediaTypes = new Set<MediaType>(["video", "audio"]);
    expect(
      filterFeed(all, state)
        .map((i) => i.uri)
        .toSorted(),
    ).toEqual(["2", "4"]);
  });

  it("filters by case-insensitive text substring", () => {
    const state = emptyFilterState();
    state.text = "VIDEO";
    expect(filterFeed(all, state).map((i) => i.uri)).toEqual(["2"]);
  });

  it("trims whitespace-only search to no-op", () => {
    const state = emptyFilterState();
    state.text = "   ";
    expect(filterFeed(all, state)).toHaveLength(4);
  });

  it("combines filters as AND across axes", () => {
    const state = emptyFilterState();
    state.artists = new Set(["lou"]);
    state.mediaTypes = new Set<MediaType>(["image"]);
    state.text = "sunset";
    expect(filterFeed(all, state).map((i) => i.uri)).toEqual(["1"]);
  });

  it("returns empty when no items match", () => {
    const state = emptyFilterState();
    state.text = "nothing matches this";
    expect(filterFeed(all, state)).toEqual([]);
  });
});
