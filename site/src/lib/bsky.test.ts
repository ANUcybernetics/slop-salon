import { describe, expect, it } from "vitest";
import { extractMediaTypes } from "./bsky.ts";

describe("extractMediaTypes", () => {
  it("returns empty array for no embed", () => {
    expect(extractMediaTypes(undefined)).toEqual([]);
  });

  it("detects images embed", () => {
    expect(
      extractMediaTypes({
        $type: "app.bsky.embed.images#view",
        images: [{ thumb: "t", fullsize: "f", alt: "" }],
      }),
    ).toEqual(["image"]);
  });

  it("detects video embed", () => {
    expect(
      extractMediaTypes({
        $type: "app.bsky.embed.video#view",
        playlist: "https://video.bsky.app/x.m3u8",
      }),
    ).toEqual(["video"]);
  });

  it("returns empty for external embeds", () => {
    expect(
      extractMediaTypes({
        $type: "app.bsky.embed.external#view",
        external: { uri: "https://example.com/article" },
      }),
    ).toEqual([]);
  });

  it("recurses into recordWithMedia", () => {
    expect(
      extractMediaTypes({
        $type: "app.bsky.embed.recordWithMedia#view",
        media: {
          $type: "app.bsky.embed.images#view",
          images: [{ thumb: "t", fullsize: "f", alt: "" }],
        },
      }),
    ).toEqual(["image"]);
  });

  it("returns empty for unknown embed types", () => {
    expect(extractMediaTypes({ $type: "app.bsky.embed.record#view" })).toEqual([]);
  });
});
