import { describe, expect, it } from "vitest";

import { reorder } from "../src/reorder";

describe("reorder", () => {
  it("moves an item just before the drop target", () => {
    expect(reorder(["a", "b", "c", "d"], "d", "b")).toEqual([
      "a",
      "d",
      "b",
      "c",
    ]);
    expect(reorder(["a", "b", "c"], "a", "c")).toEqual(["b", "a", "c"]);
  });

  it("dropping onto itself is a no-op-ish identity", () => {
    expect(reorder(["a", "b", "c"], "b", "b")).toEqual(["a", "b", "c"]);
  });

  it("unknown dragged id returns the list unchanged", () => {
    expect(reorder(["a", "b"], "z", "a")).toEqual(["a", "b"]);
  });

  it("unknown target appends to the end", () => {
    expect(reorder(["a", "b", "c"], "a", "zz")).toEqual(["b", "c", "a"]);
  });

  it("after=true drops past the target, reaching the last slot", () => {
    expect(reorder(["a", "b", "c"], "a", "c", true)).toEqual(["b", "c", "a"]);
    expect(reorder(["a", "b", "c", "d"], "b", "c", true)).toEqual([
      "a",
      "c",
      "b",
      "d",
    ]);
  });
});
