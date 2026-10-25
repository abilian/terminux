// @vitest-environment jsdom
// Link clicks: Cmd+click on macOS, plain Ctrl+click on Linux and Windows,
// as the docs say; and the app modifiers.

import { afterEach, describe, expect, it, vi } from "vitest";

const click = (init: MouseEventInit): MouseEvent =>
  ({ ctrlKey: false, shiftKey: false, metaKey: false, ...init }) as MouseEvent;

async function platformOn(platform: string) {
  vi.resetModules();
  vi.stubGlobal("navigator", { platform });
  return import("../src/input/platform");
}

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

const key = (init: KeyboardEventInit): KeyboardEvent =>
  ({
    ctrlKey: false,
    shiftKey: false,
    altKey: false,
    metaKey: false,
    ...init,
  }) as KeyboardEvent;

describe("appMod", () => {
  it("takes Ctrl+Shift on every platform, and Cmd on macOS", async () => {
    const mac = await platformOn("MacIntel");
    expect(mac.appMod(key({ metaKey: true }))).toBe(true);
    expect(mac.appMod(key({ ctrlKey: true, shiftKey: true }))).toBe(true);
    expect(mac.appMod(key({ ctrlKey: true }))).toBe(false);
    const linux = await platformOn("Linux x86_64");
    expect(linux.appMod(key({ ctrlKey: true, shiftKey: true }))).toBe(true);
    expect(linux.appMod(key({ metaKey: true }))).toBe(false);
  });
});

describe("browserMod", () => {
  afterEach(() => {
    delete (window as { pywebview?: unknown }).pywebview;
  });

  it("is Alt+Shift on Linux and Windows, in a browser tab", async () => {
    const linux = await platformOn("Linux x86_64");
    expect(linux.browserMod(key({ altKey: true, shiftKey: true }))).toBe(true);
    expect(linux.browserMod(key({ ctrlKey: true, shiftKey: true }))).toBe(
      false,
    );
    const mac = await platformOn("MacIntel");
    expect(mac.browserMod(key({ altKey: true, shiftKey: true }))).toBe(false);
  });

  it("is off in terminux's own window", async () => {
    (window as { pywebview?: unknown }).pywebview = {};
    const linux = await platformOn("Linux x86_64");
    expect(linux.inBrowser()).toBe(false);
    expect(linux.browserMod(key({ altKey: true, shiftKey: true }))).toBe(false);
  });
});
