import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { extractImages, extractVideo, type FeedItem, pruneDeadVideos } from "./bsky.ts";

describe("extractImages", () => {
  it("returns empty array for no embed", () => {
    expect(extractImages(undefined)).toEqual([]);
  });

  it("maps an images embed", () => {
    expect(
      extractImages({
        $type: "app.bsky.embed.images#view",
        images: [{ thumb: "t", fullsize: "f", alt: "a cat" }],
      }),
    ).toEqual([{ thumb: "t", fullsize: "f", alt: "a cat" }]);
  });

  it("returns empty for a video embed", () => {
    expect(
      extractImages({
        $type: "app.bsky.embed.video#view",
        playlist: "https://video.bsky.app/x.m3u8",
      }),
    ).toEqual([]);
  });

  it("recurses into recordWithMedia", () => {
    expect(
      extractImages({
        $type: "app.bsky.embed.recordWithMedia#view",
        media: {
          $type: "app.bsky.embed.images#view",
          images: [{ thumb: "t", fullsize: "f", alt: "" }],
        },
      }),
    ).toEqual([{ thumb: "t", fullsize: "f", alt: "" }]);
  });
});

describe("extractVideo", () => {
  it("returns undefined for no embed", () => {
    expect(extractVideo(undefined)).toBeUndefined();
  });

  it("returns undefined for an images embed", () => {
    expect(
      extractVideo({
        $type: "app.bsky.embed.images#view",
        images: [{ thumb: "t", fullsize: "f", alt: "" }],
      }),
    ).toBeUndefined();
  });

  it("extracts playlist, thumbnail, alt and aspectRatio from a video embed", () => {
    expect(
      extractVideo({
        $type: "app.bsky.embed.video#view",
        playlist: "https://video.bsky.app/x.m3u8",
        thumbnail: "https://video.bsky.app/x.jpg",
        alt: "a short clip",
        aspectRatio: { width: 16, height: 9 },
      }),
    ).toEqual({
      playlist: "https://video.bsky.app/x.m3u8",
      thumbnail: "https://video.bsky.app/x.jpg",
      alt: "a short clip",
      aspectRatio: { width: 16, height: 9 },
    });
  });

  it("defaults alt to empty string and recurses into recordWithMedia", () => {
    expect(
      extractVideo({
        $type: "app.bsky.embed.recordWithMedia#view",
        media: {
          $type: "app.bsky.embed.video#view",
          playlist: "https://video.bsky.app/y.m3u8",
        },
      }),
    ).toEqual({ playlist: "https://video.bsky.app/y.m3u8", alt: "" });
  });

  it("returns undefined for external embeds", () => {
    expect(
      extractVideo({
        $type: "app.bsky.embed.external#view",
        external: { uri: "https://example.com/article" },
      }),
    ).toBeUndefined();
  });
});

describe("pruneDeadVideos", () => {
  const NOW = Date.parse("2026-06-24T12:00:00Z");
  const OLD = "2026-06-24T11:00:00Z"; // an hour old, past the grace window

  // playlist URL -> HEAD status (or "throw" for a network/CORS rejection),
  // driving the stubbed fetch below. Each item gets a unique URL so the
  // module-level liveness cache never bleeds a verdict across tests.
  const statuses = new Map<string, number | "throw">();
  let n = 0;

  function videoItem(createdAt: string, playlistStatus: number | "throw"): FeedItem {
    const playlist = `https://video.bsky.app/v${n++}/playlist.m3u8`;
    statuses.set(playlist, playlistStatus);
    return {
      uri: `at://did/app.bsky.feed.post/${n}`,
      agent: "lou",
      handle: "lou.slopsalon.art",
      text: "",
      createdAt,
      url: "https://bsky.app/x",
      isRepost: false,
      replyCount: 0,
      repostCount: 0,
      likeCount: 0,
      images: [],
      video: { playlist, alt: "", thumbnail: `${playlist}-thumb` },
    };
  }

  beforeEach(() => {
    vi.stubGlobal("fetch", (url: string, opts?: { method?: string }) => {
      expect(opts?.method).toBe("HEAD");
      const status = statuses.get(url);
      return status === "throw"
        ? Promise.reject(new TypeError("CORS"))
        : Promise.resolve({ status } as Response);
    });
  });

  afterEach(() => {
    statuses.clear();
    vi.unstubAllGlobals();
  });

  it("drops a video-only post whose playlist 404s", async () => {
    expect(await pruneDeadVideos([videoItem(OLD, 404)], NOW)).toEqual([]);
  });

  it("keeps a post whose playlist is live", async () => {
    expect(await pruneDeadVideos([videoItem(OLD, 200)], NOW)).toHaveLength(1);
  });

  it("fails open: keeps the post on a network/CORS error or non-404 status", async () => {
    const items = [videoItem(OLD, "throw"), videoItem(OLD, 500)];
    expect(await pruneDeadVideos(items, NOW)).toHaveLength(2);
  });

  it("leaves freshly posted videos alone (still transcoding), without fetching", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    expect(await pruneDeadVideos([videoItem("2026-06-24T11:58:00Z", 404)], NOW)).toHaveLength(1);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("strips only the dead video from a post that also has images", async () => {
    const items = [videoItem(OLD, 404)];
    items[0].images = [{ thumb: "t", fullsize: "f", alt: "" }];
    const [kept] = await pruneDeadVideos(items, NOW);
    expect(kept.video).toBeUndefined();
    expect(kept.images).toHaveLength(1);
  });
});
