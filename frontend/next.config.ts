import type { NextConfig } from "next";

/**
 * Static export. The application is entirely client-rendered — it holds no
 * server actions, route handlers or middleware — so it ships as files to S3
 * behind CloudFront, and talks to the API only from the browser.
 */
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
