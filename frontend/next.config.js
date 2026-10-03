/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Static export: the FastAPI backend serves the built files itself, so this
  // deploys as ONE service. API routes are not allowed with `output: 'export'`,
  // which is why the upload talks to /generate directly (see lib/api.ts).
  output: 'export',
  trailingSlash: true,
  images: { unoptimized: true },
};

module.exports = nextConfig;
