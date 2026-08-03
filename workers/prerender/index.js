const BOT_AGENTS = [
  'googlebot', 'bingbot', 'yandex', 'baiduspider', 'facebookexternalhit',
  'twitterbot', 'linkedinbot', 'whatsapp', 'slackbot', 'telegrambot',
  'discordbot', 'applebot', 'pinterest', 'redditbot', 'embedly',
  'quora link preview', 'showyoubot', 'outbrain', 'rogerbot', 'vkshare'
];

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const ua = (request.headers.get('User-Agent') || '').toLowerCase();
    const isBot = BOT_AGENTS.some(bot => ua.includes(bot));
    const isStatic = /\.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|json|xml|txt|map|pdf|zip|mp3|mp4|webp)$/i.test(url.pathname);

    // Debug endpoint
    if (url.pathname === '/_prerender-debug') {
      return new Response(JSON.stringify({
        isBot,
        userAgent: ua,
        token: env.PRERENDER_TOKEN ? 'SET' : 'MISSING',
        url: url.href,
        pathname: url.pathname
      }, null, 2), {
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // For non-bots or static files, pass through to origin
    if (!isBot || isStatic) {
      return fetch(request);
    }

    // Prerender for bots
    if (!env.PRERENDER_TOKEN) {
      console.error('PRERENDER_TOKEN not set');
      return fetch(request);
    }

    try {
      const prerenderUrl = `https://service.prerender.io/${url.href}`;

      const resp = await fetch(prerenderUrl, {
        headers: {
          'X-Prerender-Token': env.PRERENDER_TOKEN,
          'User-Agent': request.headers.get('User-Agent') || '',
        },
        cf: { cacheTtl: 86400 }
      });

      if (!resp.ok) {
        console.error(`Prerender failed: ${resp.status}`);
        return fetch(request);
      }

      const html = await resp.text();

      return new Response(html, {
        status: 200,
        headers: {
          'Content-Type': 'text/html; charset=utf-8',
          'X-Prerendered': 'true',
          'Cache-Control': 'public, max-age=86400'
        }
      });
    } catch (e) {
      console.error('Prerender error:', e);
      return fetch(request);
    }
  }
};
