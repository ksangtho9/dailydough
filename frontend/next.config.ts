import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  reactCompiler: process.env.NODE_ENV === "production",
  // Explicitly disable Pages Router to prevent Next.js from checking for it
  // This is an App Router-only project
  experimental: {
    serverActions: {
      bodySizeLimit: '2mb',
    },
  },
  // Configure Turbopack root to fix workspace detection issue
  // This helps Turbopack find the Next.js package correctly
  turbopack: {
    root: path.resolve(__dirname),
  },
  // Use webpack instead of Turbopack to avoid Pages Router check bug
  // Turbopack has a bug where it checks for Pages Router files even in App Router-only projects
  webpack: (config, { isServer }) => {
    return config;
  },
};

export default nextConfig;
