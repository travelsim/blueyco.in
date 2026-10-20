// Vercel Edge Middleware runs before static files, so "/" can serve Markdown
// to clients that ask for it. A rewrite cannot do this: index.html wins at "/".
export const config = { matcher: '/' };

export default async function middleware(request) {
  const accept = request.headers.get('accept') || '';
  if (!accept.includes('text/markdown')) {
    return; // continue to the HTML homepage
  }
  const llmsUrl = new URL('/llms.txt', request.url);
  const upstream = await fetch(llmsUrl);
  const body = await upstream.text();
  return new Response(body, {
    status: 200,
    headers: {
      'Content-Type': 'text/markdown; charset=utf-8',
      'x-markdown-tokens': '1250',
      'Vary': 'Accept',
      'Cache-Control': 'public, max-age=3600',
    },
  });
}
