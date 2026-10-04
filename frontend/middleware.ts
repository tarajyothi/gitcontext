import { NextResponse, type NextRequest } from "next/server";

// Fast server-side gate: no session cookie -> /login. The cookie's validity is enforced by the API (401 -> /login).
export function middleware(req: NextRequest) {
  if (!req.cookies.get("gc_session")) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", req.nextUrl.pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = { matcher: ["/dashboard/:path*", "/repositories/:path*"] };
