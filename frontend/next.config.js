/** Same-origin proxy: the browser only talks to /api/*, so the session cookie is first-party
 *  (no CORS, no third-party cookie issues). BACKEND_URL is server-side only and never shipped to the browser. */
module.exports = {
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${process.env.BACKEND_URL ?? "http://localhost:8000"}/:path*` }];
  },
};
