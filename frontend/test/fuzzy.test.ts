import { describe, expect, it } from "vitest";

import { fuzzyScore } from "../src/fuzzy";

describe("fuzzyScore", () => {
  it("empty query matches everything with score 0", () => {
    expect(fuzzyScore("", "anything")).toBe(0);
  });

  it("returns null when not a subsequence", () => {
    expect(fuzzyScore("xyz", "terminux")).toBeNull();
    expect(fuzzyScore("nit", "ni")).toBeNull();
  });

  it("matches a case-insensitive subsequence", () => {
    expect(fuzzyScore("TMX", "terminux")).not.toBeNull();
    expect(fuzzyScore("trmnx", "terminux")).not.toBeNull();
  });

  it("prefers contiguous / earlier matches (lower score)", () => {
    const contiguous = fuzzyScore("term", "terminux")!;
    const scattered = fuzzyScore("term", "the apartment");
    expect(scattered).not.toBeNull();
    expect(contiguous).toBeLessThan(scattered as number);
  });

  it("breaks ties toward shorter labels", () => {
    const short = fuzzyScore("ab", "ab")!;
    const long = fuzzyScore("ab", "ab_long_label")!;
    expect(short).toBeLessThan(long);
  });
});
