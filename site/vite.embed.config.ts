import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: false,
    cssCodeSplit: false,
    minify: true,
    sourcemap: true,
    target: "es2022",
    lib: {
      entry: resolve(import.meta.dirname, "src/embed/slop-feed.ts"),
      formats: ["es"],
      fileName: () => "embed.js",
    },
  },
  server: {
    fs: {
      allow: [".."],
    },
  },
});
