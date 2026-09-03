import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8008",
    },
  },
  build: {
    // FastAPI (app/main.py) serves the built SPA from backend/static - it
    // resolves that path as "<app/main.py's dir>/../static", i.e.
    // backend/app/../static = backend/static. This must match that.
    outDir: "../backend/static",
    emptyOutDir: true,
  },
});
