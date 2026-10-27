import { ApiError } from '@/api/errors';
import type { components } from '@/api/schema';
import type { TokenStore } from '@/auth/token-store';

export type TokenPair = components['schemas']['TokenPair'];

type Deps = {
  store: TokenStore;
  /** POST /auth/refresh without the auth layer; throws ApiError */
  requestRefresh: (refreshToken: string) => Promise<TokenPair>;
  /** Sends a request as it is (the network) */
  send: (request: Request) => Promise<Response>;
  now?: () => number;
};

// Refresh a little before the 15 min access token expires, so it never expires in flight
const EXPIRY_MARGIN_MS = 30_000;

// Routes that must not carry (or wait for) an access token
const PUBLIC_PATHS = ['/auth/login', '/auth/register', '/auth/refresh', '/auth/password/', '/auth/google', '/auth/apple', '/health'];

function isPublic(url: string): boolean {
  const path = url.replace(/^[a-z]+:\/\/[^/]+/i, '').split('?')[0];
  return PUBLIC_PATHS.some((publicPath) => path.includes(publicPath));
}

/**
 * The only place that touches tokens (M-03). The refresh token lives in the secure store,
 * the access token only in memory. Rotation: each refresh returns a new pair and the old
 * refresh token stops working, so concurrent 401s share one refresh request.
 */
export function createAuthManager({ store, requestRefresh, send, now = Date.now }: Deps) {
  let access: { token: string; expiresAt: number } | null = null;
  let refreshing: Promise<string | null> | null = null;
  const signedOutListeners = new Set<() => void>();

  async function saveTokens(pair: TokenPair) {
    access = { token: pair.access_token, expiresAt: now() + pair.expires_in * 1000 };
    await store.setRefreshToken(pair.refresh_token);
  }

  async function clear() {
    access = null;
    await store.clear();
  }

  /** New access token, or null when the session is over (the user must sign in) */
  function refresh(): Promise<string | null> {
    if (!refreshing) {
      refreshing = (async () => {
        const refreshToken = await store.getRefreshToken();
        if (!refreshToken) {
          return null;
        }
        try {
          const pair = await requestRefresh(refreshToken);
          await saveTokens(pair);
          return pair.access_token;
        } catch (error) {
          // 401: refresh token expired, revoked or reused. Network errors keep the session.
          if (error instanceof ApiError && error.status === 401) {
            await clear();
            signedOutListeners.forEach((listener) => listener());
            return null;
          }
          throw error;
        }
      })().finally(() => {
        refreshing = null;
      });
    }
    return refreshing;
  }

  async function getAccessToken(): Promise<string | null> {
    if (access && access.expiresAt - EXPIRY_MARGIN_MS > now()) {
      return access.token;
    }
    return refresh();
  }

  /** Transport for the API client: adds the token, refreshes once on 401 and retries */
  async function authorizedFetch(request: Request): Promise<Response> {
    if (isPublic(request.url)) {
      return send(request);
    }
    const attempt = (token: string | null) => {
      const copy = request.clone(); // a body can be read only once, so each attempt gets a copy
      if (token) {
        copy.headers.set('Authorization', `Bearer ${token}`);
      }
      return send(copy);
    };

    const response = await attempt(await getAccessToken());
    if (response.status !== 401) {
      return response;
    }
    access = null;
    const newToken = await refresh();
    return newToken ? attempt(newToken) : response;
  }

  return {
    saveTokens,
    clear,
    refresh,
    getAccessToken,
    authorizedFetch,
    hasStoredSession: async () => (await store.getRefreshToken()) !== null,
    getRefreshToken: () => store.getRefreshToken(),
    /** Called when a refresh fails with 401 during use; returns an unsubscribe function */
    onSignedOut(listener: () => void) {
      signedOutListeners.add(listener);
      return () => {
        signedOutListeners.delete(listener);
      };
    },
  };
}

export type AuthManager = ReturnType<typeof createAuthManager>;
