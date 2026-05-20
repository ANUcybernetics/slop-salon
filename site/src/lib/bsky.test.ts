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

  it("detects audio from known external hosts", () => {
    const hosts = [
      "https://soundcloud.com/foo/bar",
      "https://artist.bandcamp.com/track/x",
      "https://open.spotify.com/track/x",
      "https://music.apple.com/x",
      "https://audius.co/track/x",
      "https://suno.com/song/x",
    ];
    for (const uri of hosts) {
      expect(
        extractMediaTypes({
          $type: "app.bsky.embed.external#view",
          external: { uri },
        }),
      ).toEqual(["audio"]);
    }
  });

  it("returns empty for non-audio external embeds", () => {
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

  it("ignores malformed external URIs", () => {
    expect(
      extractMediaTypes({
        $type: "app.bsky.embed.external#view",
        external: { uri: "not a url" },
      }),
    ).toEqual([]);
  });
});
