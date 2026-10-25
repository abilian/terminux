// @vitest-environment jsdom
// Sidebar show/hide + persisted layout: toggling hides the sidebar and
// PATCHes the pref; applyLayout applies the persisted state silently.

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  api: vi.fn((..._args: unknown[]) => Promise.resolve({})),
  ui: {
    sidebar_width: 300,
    sidebar_collapsed: false,
    font_size: 13,
    copy_on_select: false,
    scrollback_persist: true,
  },
}));
vi.mock("../src/state/api", () => ({
  api: mocks.api,
  TOKEN: "t",
  send: (method: string, path: string, body?: object) =>
    mocks.api(path, { method, body: body && JSON.stringify(body) }),
}));
vi.mock("../src/state/store", () => ({ getState: () => ({ ui: mocks.ui }) }));

type Layout = typeof import("../src/ui/layout");
let layout: Layout;

beforeEach(async () => {
  vi.resetModules();
  layout = await import("../src/ui/layout");
  document.body.innerHTML =
    '<aside id="sidebar" style="display: flex"></aside><div id="divider"></div>';
  mocks.api.mockClear();
  mocks.ui.sidebar_collapsed = false;
});

describe("layout", () => {
  it("toggle hides then shows the sidebar, persisting each flip", () => {
    const sidebar = document.getElementById("sidebar")!;
    layout.toggleSidebar();
    expect(sidebar.style.display).toBe("none");
    layout.toggleSidebar();
    expect(sidebar.style.display).toBe("flex");
    const bodies = mocks.api.mock.calls.map((c: unknown[]) =>
      JSON.parse((c[1] as { body: string }).body),
    );
    expect(bodies).toEqual([
      { sidebar_collapsed: true },
      { sidebar_collapsed: false },
    ]);
  });

  it("applyLayout applies persisted width and collapse without re-persisting", () => {
    mocks.ui.sidebar_collapsed = true;
    layout.applyLayout();
    const sidebar = document.getElementById("sidebar")!;
    expect(sidebar.style.width).toBe("300px");
    expect(sidebar.style.display).toBe("none");
    expect(mocks.api).not.toHaveBeenCalled();
  });
});
