import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development, API calls are forwarded to the Python server.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
