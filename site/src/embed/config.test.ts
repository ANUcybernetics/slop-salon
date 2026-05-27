import { describe, expect, it } from "vitest";
import {
  parseAgentNames,
  parsePositiveInt,
  parseRefreshIntervalMs,
  POST_LIMIT_DEFAULT,
  REFRESH_INTERVAL_DEFAULT_SECONDS,
} from "./config.ts";

describe("parseAgentNames", () => {
  it("returns null for null", () => {
    expect(parseAgentNames(null)).toBeNull();
  });

  it("returns null for an empty string", () => {
    expect(parseAgentNames("")).toBeNull();
  });

  it("returns null for whitespace-only or comma-only input", () => {
    expect(parseAgentNames("   ")).toBeNull();
    expect(parseAgentNames(",,,")).toBeNull();
  });

  it("parses a comma-separated list", () => {
    const result = parseAgentNames("lou,mina");
    expect(result).toEqual(new Set(["lou", "mina"]));
  });

  it("trims whitespace around each name and drops empties", () => {
    const result = parseAgentNames(" lou , mina ,, gert ");
    expect(result).toEqual(new Set(["lou", "mina", "gert"]));
  });
});

describe("parsePositiveInt", () => {
  it("uses the fallback when the attribute is absent", () => {
    expect(parsePositiveInt(null, POST_LIMIT_DEFAULT)).toBe(POST_LIMIT_DEFAULT);
  });

  it("parses a valid positive integer", () => {
    expect(parsePositiveInt("42", 10)).toBe(42);
  });

  it("falls back on non-numeric input", () => {
    expect(parsePositiveInt("abc", 10)).toBe(10);
  });

  it("falls back on zero or negative input", () => {
    expect(parsePositiveInt("0", 10)).toBe(10);
    expect(parsePositiveInt("-5", 10)).toBe(10);
  });
});

describe("parseRefreshIntervalMs", () => {
  it("returns the default in ms when the attribute is absent", () => {
    expect(parseRefreshIntervalMs(null)).toBe(REFRESH_INTERVAL_DEFAULT_SECONDS * 1000);
  });

  it("converts seconds to ms", () => {
    expect(parseRefreshIntervalMs("60")).toBe(60_000);
  });

  it("returns 0 to disable polling", () => {
    expect(parseRefreshIntervalMs("0")).toBe(0);
  });

  it("falls back on invalid input", () => {
    expect(parseRefreshIntervalMs("nope")).toBe(REFRESH_INTERVAL_DEFAULT_SECONDS * 1000);
    expect(parseRefreshIntervalMs("-1")).toBe(REFRESH_INTERVAL_DEFAULT_SECONDS * 1000);
  });
});
