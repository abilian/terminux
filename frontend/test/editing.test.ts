import { describe, expect, it } from "vitest";

import { macEditingSeq } from "../src/editing";

function ev(p: Partial<KeyboardEvent>): KeyboardEvent {
  return {
    key: "",
    metaKey: false,
    altKey: false,
    ctrlKey: false,
    shiftKey: false,
    ...p,
  } as KeyboardEvent;
}

describe("macEditingSeq", () => {
  it("maps Cmd line chords", () => {
    expect(macEditingSeq(ev({ metaKey: true, key: "ArrowLeft" }))).toBe("\x01");
    expect(macEditingSeq(ev({ metaKey: true, key: "ArrowRight" }))).toBe(
      "\x05",
    );
    expect(macEditingSeq(ev({ metaKey: true, key: "Backspace" }))).toBe("\x15");
  });

  it("maps Option word chords", () => {
    expect(macEditingSeq(ev({ altKey: true, key: "ArrowLeft" }))).toBe("\x1bb");
    expect(macEditingSeq(ev({ altKey: true, key: "ArrowRight" }))).toBe(
      "\x1bf",
    );
    expect(macEditingSeq(ev({ altKey: true, key: "Backspace" }))).toBe("\x17");
    expect(macEditingSeq(ev({ altKey: true, key: "Delete" }))).toBe("\x1bd");
  });

  it("yields null for Shift/Ctrl (reserved for navigation/shell)", () => {
    expect(
      macEditingSeq(ev({ metaKey: true, shiftKey: true, key: "ArrowLeft" })),
    ).toBeNull();
    expect(macEditingSeq(ev({ ctrlKey: true, key: "ArrowLeft" }))).toBeNull();
    expect(macEditingSeq(ev({ key: "ArrowLeft" }))).toBeNull();
    expect(macEditingSeq(ev({ metaKey: true, key: "a" }))).toBeNull();
  });
});
