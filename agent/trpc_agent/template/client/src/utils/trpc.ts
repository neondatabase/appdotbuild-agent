import { createTRPCClient, httpBatchLink, loggerLink } from '@trpc/client';
import type { AppRouter } from '../../../server/src';
import superjson from 'superjson';

const BASE_URL = process.env.NODE_ENV === 'production' ? '/api' : 'http://localhost:2022/';

export const trpc = createTRPCClient<AppRouter>({
  links: [
    httpBatchLink({ url: BASE_URL, transformer: superjson, fetch: (url, options) => {
      return fetch(url, {
        ...options,
        credentials: 'include',
      });
    },
}),
    loggerLink({
          enabled: (opts) =>
            (typeof window !== 'undefined') ||
            (opts.direction === 'down' && opts.result instanceof Error),
        }),
  ],
});
