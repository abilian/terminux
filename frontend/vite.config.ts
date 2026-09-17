/// <reference types="vitest/config" />
import { defineConfig } from "vite";

// The built bundle is served by the Python backend, so emit it into the
// package tree (committed; rebuilt via `make frontend`). Hashed asset names
// land under /assets and are served by Starlette's StaticFiles mount.
export default defineConfig({
  base: "/",
  build: {
    outDir: "../src/terminux/web/static",
    emptyOutDir: true,
    assetsDir: "assets",
    // Support floor: the WKWebView of the oldest macOS we serve (Big Sur ≈
    // Safari 14) — desktop windows and --connect clients run whatever WebKit
    // the OS ships, and remote-mode browsers can be old too. Keep this (and
    // dependency floors — xterm is pinned to the 5.x line for the same
    // reason) below anything that would silently drop those machines.
    target: ["es2020", "safari14"],
    sourcemap: false,
  },
  test: {
    coverage: {
      // Report against every source file, not only the ones tests import —
      // otherwise the rate flatters itself by ignoring untested modules.
      include: ["src/**/*.{ts,tsx}"],
    },
  },
});
