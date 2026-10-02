export const dynamic = 'force-dynamic';

export function GET(request: Request): Response {
  const expected = process.env.RLB_DESKTOP_FRONTEND_TOKEN;
  if (!expected || request.headers.get('x-rlb-desktop-nonce') !== expected) {
    return new Response(null, { status: 404, headers: { 'Cache-Control': 'no-store' } });
  }
  return Response.json({ ready: true }, { headers: { 'Cache-Control': 'no-store' } });
}
