import { afterEach, describe, expect, it, vi } from "vitest";

import { _reset, has, invoke, register } from "../src/commands";

afterEach(() => _reset());

describe("commands bus", () => {
  it("invokes a registered command and reports true", () => {
    let called = 0;
    register("test.ping", () => {
      called += 1;
    });
    expect(invoke("test.ping")).toBe(true);
    expect(called).toBe(1);
  });

  it("returns false and warns for an unknown command", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(invoke("test.missing")).toBe(false);
    expect(warn).toHaveBeenCalledOnce();
    warn.mockRestore();
  });

  it("warns when a command id is registered twice", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    register("test.dup", () => {});
    register("test.dup", () => {});
    expect(warn).toHaveBeenCalledOnce();
    warn.mockRestore();
  });

  it("has() reports registry membership", () => {
    register("test.exists", () => {});
    expect(has("test.exists")).toBe(true);
    expect(has("test.missing")).toBe(false);
  });

  it("the registered handler can be async; invoke does not await", async () => {
    let resolved = false;
    register("test.async", async () => {
      await Promise.resolve();
      resolved = true;
    });
    expect(invoke("test.async")).toBe(true);
    // fire-and-forget: not yet resolved at the synchronous return.
    expect(resolved).toBe(false);
    await Promise.resolve(); // microtask flush
    expect(resolved).toBe(true);
  });
});
