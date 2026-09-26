import type { NextConfig } from "next";

// The Python API. Resolved at build time, so Docker builds pass it as a build arg.
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  reactCompiler: true,
  async rewrites() {
    return {
      beforeFiles: [],
      afterFiles: [],
      // Fallback runs only when no Next.js route matches, so gateway routes
      // added under /api (Phase 2) take precedence over the Python API.
      fallback: [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }],
    };
  },
};

export default nextConfig;
