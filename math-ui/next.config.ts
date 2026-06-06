import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Transpile the in-repo @aiplatform/sdk — it ships compiled JS in
  // dist/, but Next 16 still needs explicit opt-in for file: deps so
  // the typed module resolution kicks in.
  transpilePackages: ["@aiplatform/sdk"],
};

export default nextConfig;
