import { NextResponse, type NextRequest } from "next/server";

// (Next 16 renamed the "middleware" file convention to "proxy".) Fast server-side gate: no session cookie -> /login. The cookie's validity is enforced by the API (401 -> /login).
// Behind a TLS-terminating proxy the URL Next sees is http://<internal>, so the redirect is built from the public
// Host header and X-Forwarded-Proto (set by Caddy). Next requires an absolute URL here.
export function proxy(req: NextRequest) {
  if (!req.cookies.get("gc_session")) {
    const proto = req.headers.get("x-forwarded-proto")?.split(",")[0].trim() || req.nextUrl.protocol.replace(":", "");
    const host = req.headers.get("host") || req.nextUrl.host;
    const url = new URL(`/login?next=${encodeURIComponent(req.nextUrl.pathname)}`, `${proto}://${host}`);
    return NextResponse.redirect(url, 307);
  }
  return NextResponse.next();
}

export const config = { matcher: ["/dashboard/:path*", "/repositories/:path*"] };
