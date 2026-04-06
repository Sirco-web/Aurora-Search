/**
 * Cloudflare Worker Proxy for Aurora Search
 * Deploy this to Cloudflare Workers to use as a proxy
 * 
 * SETUP INSTRUCTIONS:
 * 1. Go to https://workers.cloudflare.com/
 * 2. Create a new Worker
 * 3. Copy this entire code into the Worker editor
 * 4. Save and deploy
 * 5. Copy your Worker URL: https://YOUR-WORKER-NAME.workers.dev
 * 6. Add to config.txt: proxy_list = https://YOUR-WORKER-NAME.workers.dev|
 * 
 * BACKUP CLOUDFLARE WORKER:
 * If you need a ready-to-use worker, use this backup:
 * https://crawler-23436223-fufbwqrf-sirco.timco-store1.workers.dev/
 * 
 * In config.txt:
 *   proxy_list = https://crawler-23436223-fufbwqrf-sirco.timco-store1.workers.dev|
 *   use_proxy = true
 */

export default {
  async fetch(request) {
    try {
      // Get the target URL from the request
      const url = new URL(request.url);
      const targetUrl = url.searchParams.get('url');
      
      if (!targetUrl) {
        return new Response(JSON.stringify({ error: 'No URL provided' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      // Validate URL format
      try {
        new URL(targetUrl);
      } catch {
        return new Response(JSON.stringify({ error: 'Invalid URL' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' }
        });
      }

      // Fetch the target URL through Cloudflare
      const response = await fetch(targetUrl, {
        method: request.method,
        headers: {
          // Set a user agent
          'User-Agent': 'Aurora-Search-Bot/1.0 (+https://github.com/Sirco-web/Aurora-Search)',
          // Remove hop-by-hop headers
          'Connection': 'close',
        },
        // Timeout after 30 seconds
        cf: {
          cacheEverything: false,
          minify: {
            javascript: false,
            css: false,
            html: false,
          }
        }
      });

      // Return the response
      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: new Headers({
          'Content-Type': response.headers.get('Content-Type') || 'text/html',
          'Cache-Control': 'no-cache',
          'X-Proxy': 'Aurora-Search-Cloudflare-Worker'
        })
      });

    } catch (error) {
      return new Response(JSON.stringify({ 
        error: 'Fetch failed',
        message: error.message 
      }), {
        status: 502,
        headers: { 'Content-Type': 'application/json' }
      });
    }
  }
};

/**
 * USAGE EXAMPLES:
 * 
 * Direct proxy usage (return HTML):
 * curl "https://YOUR-WORKER-NAME.workers.dev?url=https://example.com"
 *
 * With Aurora Search crawler:
 * Add to config.txt:
 *   proxy_list = https://YOUR-WORKER-NAME.workers.dev|
 *   use_proxy = true
 * 
 * The crawler will automatically route requests through your Worker!
 */
