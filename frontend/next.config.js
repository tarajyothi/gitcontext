/** Same-origin proxy in dev (and on platforms without a front proxy): the browser only talks to /api/*.
 *  BACKEND_URL is read at BUILD time for `output: "standalone"` (Docker: pass --build-arg BACKEND_URL=...).
 *  With the bundled Caddy proxy, /api/* is routed before it ever reaches Next. */
const isProd = process.env.NODE_ENV === "production";
const csp = [
  "default-src 'self'", "script-src 'self' 'unsafe-inline'", "style-src 'self' 'unsafe-inline'", "img-src 'self' data:",
  "font-src 'self'", "connect-src 'self'", "object-src 'none'", "base-uri 'self'", "form-action 'self'", "frame-ancestors 'none'",
].join("; ");

module.exports = {
  reactStrictMode: true,
  poweredByHeader: false,
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${process.env.BACKEND_URL ?? "http://localhost:8000"}/:path*` }];
  },
  async headers() {
    if (!isProd) return []; // dev server needs eval for hot reload
    return [{ source: "/:path*", headers: [
      { key: "Content-Security-Policy", value: csp }, { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "X-Frame-Options", value: "DENY" }, { key: "Referrer-Policy", value: "no-referrer" },
      { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
    ] }];
  },
};
