import { describe, expect, it } from "vitest";
import type { Agent } from "./agents.ts";
import { authorFeedResponse, extractImages, extractVideo, parseFeedEntry } from "./bsky.ts";

const lou: Agent = {
  name: "lou",
  handle: "lou.slopsalon.art",
  github_repo: "ANUcybernetics/slop-salon-lou",
  sprite_id: "lou",
  salon: "one",
  soul: "boden",
  live: true,
  namesake: "",
  namesake_url: "",
};

const post = {
  uri: "at://did:plc:lou/app.bsky.feed.post/abc",
  cid: "bafy",
  author: { did: "did:plc:lou", handle: "lou.slopsalon.art" },
  record: {
    text: "a study",
    createdAt: "2026-09-11T00:00:00.000Z",
    provenance: { model: "z-ai/glm-5.3-flash", salon: "glm-flash" },
  },
  indexedAt: "2026-09-11T00:00:01.000Z",
  likeCount: 2,
  embed: {
    $type: "app.bsky.embed.images#view",
    images: [{ thumb: "t", fullsize: "f", alt: "a cat" }],
  },
};

describe("parseFeedEntry", () => {
  it("maps a valid entry, including the provenance stamp", () => {
    const item = parseFeedEntry(lou, { post });
    expect(item).toMatchObject({
      uri: post.uri,
      agent: "lou",
      text: "a study",
      createdAt: "2026-09-11T00:00:00.000Z",
      url: "https://bsky.app/profile/lou.slopsalon.art/post/abc",
      isRepost: false,
      model: "z-ai/glm-5.3-flash",
      likeCount: 2,
      replyCount: 0,
    });
    expect(item?.images).toEqual([{ thumb: "t", fullsize: "f", alt: "a cat" }]);
  });

  it("tolerates a post with no provenance and unknown extra fields", () => {
    const item = parseFeedEntry(lou, {
      post: { ...post, record: { text: "x", createdAt: "2026-09-11T00:00:00Z", langs: ["en"] } },
    });
    expect(item?.model).toBeUndefined();
  });

  it("marks reposts", () => {
    const item = parseFeedEntry(lou, {
      post,
      reason: { $type: "app.bsky.feed.defs#reasonRepost" },
    });
    expect(item?.isRepost).toBe(true);
  });

  it("drops an entry that does not parse rather than throwing", () => {
    expect(parseFeedEntry(lou, { post: { uri: 42 } })).toBeNull();
    expect(parseFeedEntry(lou, "garbage")).toBeNull();
  });

  it("accepts an unknown embed type", () => {
    const item = parseFeedEntry(lou, {
      post: { ...post, embed: { $type: "app.bsky.embed.external#view", external: { uri: "u" } } },
    });
    expect(item?.images).toEqual([]);
    expect(item?.video).toBeUndefined();
  });
});

describe("authorFeedResponse", () => {
  it("requires a feed array and keeps the cursor", () => {
    expect(authorFeedResponse.safeParse({ feed: [], cursor: "c" }).success).toBe(true);
    expect(authorFeedResponse.safeParse({ posts: [] }).success).toBe(false);
  });
});

describe("extractImages / extractVideo", () => {
  it("returns empty for no embed", () => {
    expect(extractImages(undefined)).toEqual([]);
    expect(extractVideo(undefined)).toBeUndefined();
  });

  it("recurses into recordWithMedia", () => {
    const media = {
      $type: "app.bsky.embed.video#view" as const,
      playlist: "https://video.bsky.app/x.m3u8",
      thumbnail: "https://video.bsky.app/x.jpg",
      aspectRatio: { width: 16, height: 9 },
    };
    expect(extractVideo({ $type: "app.bsky.embed.recordWithMedia#view", media })).toEqual({
      playlist: media.playlist,
      thumbnail: media.thumbnail,
      alt: "",
      aspectRatio: { width: 16, height: 9 },
    });
    expect(extractImages({ $type: "app.bsky.embed.recordWithMedia#view", media })).toEqual([]);
  });
});
