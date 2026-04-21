import { defineConfig } from "vite";

export default defineConfig({
  build: {
    outDir: "dist",
    rollupOptions: {
      input: {
        taskpane: "src/taskpane/index.html"
      }
    }
  },
  test: {
    environment: "node"
  }
});
