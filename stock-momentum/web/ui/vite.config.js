import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Built into ../static/dist and committed, so the mini PC needs no Node.
// See ui/README.md for how to rebuild.
export default defineConfig({
  plugins: [vue()],
  base: "/static/dist/",
  build: {
    outDir: "../static/dist",
    emptyOutDir: true,
    // One JS and one CSS file keeps the Flask static route simple and the
    // committed diff readable.
    rollupOptions: {
      output: {
        entryFileNames: "app.js",
        chunkFileNames: "app-[name].js",
        assetFileNames: "app.[ext]",
      },
    },
  },
});
