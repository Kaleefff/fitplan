import { ApiError } from '@/api/errors';
import { createAuthManager, type TokenPair } from '@/auth/auth-manager';
import type { TokenStore } from '@/auth/token-store';

const API = 'http://api.test/api/v1';

function memoryStore(initial: string | null = null): TokenStore & { value: string | null } {
  const store = {
    value: initial,
    getRefreshToken: async () => store.value,
    setRefreshToken: async (token: string) => {
      store.value = token;
    },
    clear: async () => {
      store.value = null;
    },
  };
  return store;
}

function pair(n: number): TokenPair {
  return { access_token: `access-${n}`, refresh_token: `refresh-${n}`, token_type: 'bearer', expires_in: 900 };
}

type FakeServer = {
  validAccess: string;
  seenTokens: (string | null)[];
  send: (request: Request) => Promise<Response>;
};

/** Answers 200 for the access token it currently accepts and 401 for anything else */
function fakeServer(): FakeServer {
  const server: FakeServer = {
    validAccess: 'access-1',
    seenTokens: [],
    send: async (request) => {
      const header = request.headers.get('Authorization');
      server.seenTokens.push(header);
      const ok: boolean = request.url.includes('/auth/') || header === `Bearer ${server.validAccess}`;
      return new Response(ok ? '{}' : '{"code":"unauthorized","message":"x","details":[]}', {
        status: ok ? 200 : 401,
      });
    },
  };
  return server;
}

describe('createAuthManager', () => {
  it('adds the access token to API requests', async () => {
    const server = fakeServer();
    const auth = createAuthManager({ store: memoryStore(), send: server.send, requestRefresh: jest.fn() });
    await auth.saveTokens(pair(1));
    const response = await auth.authorizedFetch(new Request(`${API}/users/me`));
    expect(response.status).toBe(200);
    expect(server.seenTokens).toEqual(['Bearer access-1']);
  });

  it('sends login and register without a token', async () => {
    const server = fakeServer();
    const auth = createAuthManager({ store: memoryStore(), send: server.send, requestRefresh: jest.fn() });
    await auth.saveTokens(pair(1));
    await auth.authorizedFetch(new Request(`${API}/auth/login`, { method: 'POST', body: '{}' }));
    expect(server.seenTokens).toEqual([null]);
  });

  it('refreshes an expired token transparently and stores the rotated refresh token', async () => {
    const server = fakeServer();
    const store = memoryStore();
    const requestRefresh = jest.fn(async () => pair(2));
    const auth = createAuthManager({ store, send: server.send, requestRefresh });
    await auth.saveTokens(pair(1));
    server.validAccess = 'access-2'; // the server no longer accepts access-1

    const response = await auth.authorizedFetch(
      new Request(`${API}/users/me`, { method: 'PATCH', body: '{"name":"Ola"}' }),
    );

    expect(response.status).toBe(200);
    expect(requestRefresh).toHaveBeenCalledWith('refresh-1');
    expect(store.value).toBe('refresh-2');
    expect(server.seenTokens).toEqual(['Bearer access-1', 'Bearer access-2']);
  });

  it('shares one refresh between concurrent requests (rotation would reject a second one)', async () => {
    let now = 0;
    const server = fakeServer();
    server.validAccess = 'access-2';
    const requestRefresh = jest.fn(async () => pair(2));
    const auth = createAuthManager({ store: memoryStore(), send: server.send, requestRefresh, now: () => now });
    await auth.saveTokens(pair(1));
    now = 901_000; // access-1 expired

    const responses = await Promise.all([
      auth.authorizedFetch(new Request(`${API}/users/me`)),
      auth.authorizedFetch(new Request(`${API}/users/me`)),
      auth.authorizedFetch(new Request(`${API}/auth/logout`, { method: 'POST', body: '{}' })),
    ]);

    expect(responses.map((r) => r.status)).toEqual([200, 200, 200]);
    expect(requestRefresh).toHaveBeenCalledTimes(1);
  });

  it('signs out when the refresh is rejected with 401', async () => {
    const server = fakeServer();
    server.validAccess = 'none';
    const store = memoryStore();
    const requestRefresh = jest.fn(async () => {
      throw new ApiError(401, 'unauthorized', 'Invalid refresh token');
    });
    const auth = createAuthManager({ store, send: server.send, requestRefresh });
    const onSignedOut = jest.fn();
    auth.onSignedOut(onSignedOut);
    await auth.saveTokens(pair(1));

    const response = await auth.authorizedFetch(new Request(`${API}/users/me`));

    expect(response.status).toBe(401);
    expect(onSignedOut).toHaveBeenCalledTimes(1);
    expect(store.value).toBeNull();
  });

  it('keeps the session when the refresh fails for lack of network', async () => {
    const store = memoryStore('refresh-1');
    const requestRefresh = jest.fn(async () => {
      throw new ApiError(0, 'network_error', 'offline');
    });
    const auth = createAuthManager({ store, send: jest.fn(), requestRefresh });
    const onSignedOut = jest.fn();
    auth.onSignedOut(onSignedOut);

    await expect(auth.refresh()).rejects.toMatchObject({ code: 'network_error' });
    expect(onSignedOut).not.toHaveBeenCalled();
    expect(store.value).toBe('refresh-1');
  });
});
