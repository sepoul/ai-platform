import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Transpile our internal TS SDK at build time — it ships source
  // TypeScript (no compile step), so Next must lift it into its own
  // bundler pipeline.
  transpilePackages: ["@sepoul-packages/sdk"],
  // The `file:` link to ../sdk-ts has to be resolved at build time
  // even when running inside Docker. The build context for the
  // platform-ui image will need to include ../sdk-ts/ alongside it.
  outputFileTracingRoot: process.env.NEXT_OUTPUT_TRACING_ROOT,
};

export default nextConfig;
