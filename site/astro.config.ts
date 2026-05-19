import { defineConfig } from "astro/config";

export default defineConfig({
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
