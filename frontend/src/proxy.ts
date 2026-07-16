import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Next.js 16 renamed `middleware` to `proxy` — this is the network-boundary
// gate, not a full auth check (the JWT is httpOnly and its validity/role is
// verified server-side on every API call). This only blocks obviously
// unauthenticated navigation to protected routes.
export function proxy(request: NextRequest) {
  const hasSession = request.cookies.has("access_token");
  const { pathname } = request.nextUrl;

  if (pathname.startsWith("/dashboard") && !hasSession) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*"],
};
