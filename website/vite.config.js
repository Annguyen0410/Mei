import { defineConfig } from "vite";
import { resolve } from "node:path";

// The site is plain HTML, one stylesheet and a few ES modules: no framework and
// no runtime dependencies. Vite is only here to serve it locally, hash the
// assets and write `dist/`.
// `base: "./"` keeps the build portable — it works from a domain root, a
// subpath (GitHub Pages project site) or a file:// snapshot without a rebuild.
export default defineConfig({
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "chrome120",
    rollupOptions: {
      input: {
        main: resolve(import.meta.dirname, "index.html"),
        notFound: resolve(import.meta.dirname, "404.html"),
        og: resolve(import.meta.dirname, "og.html"),
      },
    },
  },
  server: {
    port: 5173,
    strictPort: true,
  },
});
