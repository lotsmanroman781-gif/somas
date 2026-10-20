// Reuse the Pages gateway so both deployment modes enforce identical safeguards.
import { onRequest } from '../functions/api/[[path]].js';

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    if (path === '/api' || path.startsWith('/api/')) {
      return onRequest({ request, env });
    }
    return env.ASSETS.fetch(request);
  },
};
