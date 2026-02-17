import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
export default defineConfig(function (_a) {
    var command = _a.command;
    return ({
        // Build is served by FastAPI at /app; dev stays rooted at /
        base: command === "build" ? "/app/" : "/",
        plugins: [react()],
        server: {
            host: "127.0.0.1",
            port: 8788,
        },
        preview: {
            host: "127.0.0.1",
            port: 8788,
        },
        test: {
            environment: "jsdom",
            globals: true,
        },
    });
});
