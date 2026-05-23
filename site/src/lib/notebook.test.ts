import { describe, expect, it } from "vitest";
import { compareNotes, snippetOf } from "./notebook.ts";

describe("compareNotes", () => {
  it("orders newer dates first", () => {
    const names = ["tick-2026-05-19.md", "tick-2026-05-22.md", "tick-2026-05-20.md"];
    expect(names.toSorted(compareNotes)).toEqual([
      "tick-2026-05-22.md",
      "tick-2026-05-20.md",
      "tick-2026-05-19.md",
    ]);
  });

  it("orders within a day by tick-suffix length, then by suffix", () => {
    const names = [
      "tick-2026-05-20.md",
      "tick-2026-05-20a.md",
      "tick-2026-05-20z.md",
      "tick-2026-05-20aa.md",
      "tick-2026-05-20ab.md",
    ];
    expect(names.toSorted(compareNotes)).toEqual([
      "tick-2026-05-20ab.md",
      "tick-2026-05-20aa.md",
      "tick-2026-05-20z.md",
      "tick-2026-05-20a.md",
      "tick-2026-05-20.md",
    ]);
  });

  it("interleaves tick-named and slug-named notes by date", () => {
    const names = [
      "2026-05-19-foo.md",
      "tick-2026-05-22w.md",
      "2026-05-22-bar.md",
      "tick-2026-05-22.md",
      "2026-05-22-aaa.md",
    ];
    expect(names.toSorted(compareNotes)).toEqual([
      // 2026-05-22 first, tick-with-suffix beats slug-only, then slug alphabetical
      "tick-2026-05-22w.md",
      "tick-2026-05-22.md",
      "2026-05-22-aaa.md",
      "2026-05-22-bar.md",
      "2026-05-19-foo.md",
    ]);
  });
});

describe("snippetOf", () => {
  it("strips the leading H1 and returns the first paragraph", () => {
    const md = "# tick 2026-05-22w\n\nFirst paragraph here.\n\nSecond paragraph.";
    expect(snippetOf(md)).toBe("First paragraph here.");
  });

  it("skips heading-only paragraphs and picks the next prose", () => {
    const md = "# tick 2026-05-22v\n\n## State\n\nGhost orbit thread at peak density.";
    expect(snippetOf(md)).toBe("Ghost orbit thread at peak density.");
  });

  it("strips a heading attached to a paragraph (no blank line between)", () => {
    const md = "# tick 1\n\n## State\nGhost orbit at peak density.";
    expect(snippetOf(md)).toBe("Ghost orbit at peak density.");
  });

  it("strips leading YAML frontmatter", () => {
    const md =
      "---\ndate: 2026-05-23T00:10\npost: at://did:plc:abc/x\n---\n\nFirst real paragraph.";
    expect(snippetOf(md)).toBe("First real paragraph.");
  });

  it("flattens markdown emphasis and inline code", () => {
    const md = "# x\n\nA *bold* sentence with `code` and a [link](http://x).";
    expect(snippetOf(md)).toBe("A bold sentence with code and a link.");
  });

  it("truncates long paragraphs with an ellipsis", () => {
    const md = "# x\n\n" + "lorem ".repeat(80);
    const out = snippetOf(md);
    expect(out.endsWith("…")).toBe(true);
    expect(out.length).toBeLessThanOrEqual(218);
  });
});
