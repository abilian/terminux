import { describe, expect, it, vi } from "vitest";

import { createKitty } from "../src/kitty";

describe("createKitty", () => {
  it("answers a flags query with the current flags", () => {
    const k = createKitty();
    const sent: string[] = [];
    k.scan("\x1b[?u", (s) => sent.push(s));
    expect(sent).toEqual(["\x1b[?0u"]);
    expect(k.enabled).toBe(false);
  });

  it("enables on push and disables on pop", () => {
    const k = createKitty();
    k.scan("\x1b[>5u", vi.fn());
    expect(k.enabled).toBe(true);
    expect(k.flags).toBe(5);
    k.scan("\x1b[<u", vi.fn());
    expect(k.enabled).toBe(false);
    expect(k.flags).toBe(0);
  });

  it("encodes modified Enter only when enabled", () => {
    const k = createKitty();
    const shiftEnter = { shiftKey: true } as KeyboardEvent;
    expect(k.encodeEnter(shiftEnter)).toBeNull(); // not negotiated yet
    k.scan("\x1b[>1u", vi.fn());
    expect(k.encodeEnter(shiftEnter)).toBe("\x1b[13;2u");
    expect(k.encodeEnter({} as KeyboardEvent)).toBeNull(); // plain Enter
  });
});
