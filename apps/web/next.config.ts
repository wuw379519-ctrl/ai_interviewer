import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  async headers() {
    return [{ source: "/(.*)", headers: [{ key: "Permissions-Policy", value: "camera=(self), microphone=(self), on-device-speech-recognition=(self)" }] }];
  },
  // workspace 包直接以 TS 源码形式被引用，交给 Next 编译，避免维护一套额外构建产物
  transpilePackages: ["@aii/core"],
  eslint: {
    // lint 由根目录统一执行（pnpm lint），避免 next build 期间重复且规则不一致
    ignoreDuringBuilds: true,
  },
  webpack(config) {
    // Local shim: ticket forbids adding the npm `server-only` package to the lockfile.
    config.resolve.alias = {
      ...config.resolve.alias,
      "server-only": path.join(__dirname, "shims/server-only.ts"),
    };
    return config;
  },
};

export default nextConfig;
