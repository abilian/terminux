// Link clicks: Cmd+click on macOS, plain Ctrl+click on Linux and Windows,
// as the docs say.

import { afterEach, describe, expect, it, vi } from "vitest";

const click = (init: MouseEventInit): MouseEvent =>
  ({ ctrlKey: false, shiftKey: false, metaKey: false, ...init }) as MouseEvent;

async function linkModOn(platform: string) {
  vi.resetModules();
  vi.stubGlobal("navigator", { platform });
  return (await import("../src/input/platform")).linkMod;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("linkMod", () => {
  it("opens on Ctrl+click on Linux and Windows, not on Cmd+click", async () => {
    for (const platform of ["Linux x86_64", "Win32"]) {
      const linkMod = await linkModOn(platform);
      expect(linkMod(click({ ctrlKey: true }))).toBe(true);
      expect(linkMod(click({ ctrlKey: true, shiftKey: true }))).toBe(true);
      expect(linkMod(click({ metaKey: true }))).toBe(false);
      expect(linkMod(click({}))).toBe(false);
    }
  });

  it("opens on Cmd+click on macOS, leaving Ctrl+click alone", async () => {
    const linkMod = await linkModOn("MacIntel");
    expect(linkMod(click({ metaKey: true }))).toBe(true);
    expect(linkMod(click({ ctrlKey: true }))).toBe(false);
  });
});
