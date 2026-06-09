import { describe, expect, it } from "vitest";
import { extractImages, extractVideo } from "./bsky.ts";

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

  it("extracts playlist, thumbnail and aspectRatio from a video embed", () => {
    expect(
      extractVideo({
        $type: "app.bsky.embed.video#view",
        playlist: "https://video.bsky.app/x.m3u8",
        thumbnail: "https://video.bsky.app/x.jpg",
        aspectRatio: { width: 16, height: 9 },
      }),
    ).toEqual({
      playlist: "https://video.bsky.app/x.m3u8",
      thumbnail: "https://video.bsky.app/x.jpg",
      aspectRatio: { width: 16, height: 9 },
    });
  });

  it("recurses into recordWithMedia", () => {
    expect(
      extractVideo({
        $type: "app.bsky.embed.recordWithMedia#view",
        media: {
          $type: "app.bsky.embed.video#view",
          playlist: "https://video.bsky.app/y.m3u8",
        },
      }),
    ).toEqual({ playlist: "https://video.bsky.app/y.m3u8" });
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
