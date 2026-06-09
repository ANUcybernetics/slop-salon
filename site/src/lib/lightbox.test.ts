import { describe, expect, it } from "vitest";
import { toGalleryItem } from "./lightbox.ts";

describe("toGalleryItem", () => {
  it("maps an image anchor: full size comes from the href", () => {
    expect(
      toGalleryItem({
        kind: "image",
        href: "https://cdn/full.jpg",
        imgSrc: "https://cdn/thumb.jpg",
        alt: "a cat",
      }),
    ).toEqual({
      kind: "image",
      src: "https://cdn/thumb.jpg",
      full: "https://cdn/full.jpg",
      alt: "a cat",
    });
  });

  it("maps a video anchor: poster is shown and the playlist is carried", () => {
    expect(
      toGalleryItem({
        kind: "video",
        href: "https://bsky.app/profile/x/post/1",
        imgSrc: "https://cdn/poster.jpg",
        alt: "a clip",
        playlist: "https://video.bsky.app/p.m3u8",
      }),
    ).toEqual({
      kind: "video",
      src: "https://cdn/poster.jpg",
      full: "https://cdn/poster.jpg",
      alt: "a clip",
      playlist: "https://video.bsky.app/p.m3u8",
    });
  });
});
