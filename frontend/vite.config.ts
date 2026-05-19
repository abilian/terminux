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
    target: "es2022",
    sourcemap: false,
  },
});
