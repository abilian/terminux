import { describe, expect, it } from "vitest";
import { formatDuration } from "../src/util/duration";

describe("formatDuration", () => {
  it("renders seconds under a minute", () => {
    expect(formatDuration(0)).toBe("0s");
    expect(formatDuration(42)).toBe("42s");
    expect(formatDuration(59)).toBe("59s");
  });

  it("renders minutes with zero-padded seconds", () => {
    expect(formatDuration(60)).toBe("1m 00s");
    expect(formatDuration(95)).toBe("1m 35s");
    expect(formatDuration(3599)).toBe("59m 59s");
  });

  it("drops seconds past an hour and never rolls into days", () => {
    expect(formatDuration(3725)).toBe("1h 02m");
    expect(formatDuration(90061)).toBe("25h 01m");
  });

  it("clamps negatives and truncates fractions", () => {
    expect(formatDuration(-5)).toBe("0s");
    expect(formatDuration(61.9)).toBe("1m 01s");
  });
});
