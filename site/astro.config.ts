import { defineConfig } from "astro/config";

export default defineConfig({
  // Astro 7's default ("jsx") drops the line break between wrapped prose and
  // an inline element, running words into links. `true` collapses it to a space.
  compressHTML: true,
  site: "https://slopsalon.art",
  trailingSlash: "never",
  build: {
    format: "file",
  },
  vite: {
    server: {
      fs: {
        // Allow reading slop_salon.toml from the repo root (one level up).
        allow: [".."],
      },
    },
  },
});
