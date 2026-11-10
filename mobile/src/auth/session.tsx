import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';

import { api, setTransport, unwrap } from '@/api/client';
import { ApiError, toApiError, userMessage } from '@/api/errors';
import type { components } from '@/api/schema';
import { createAuthManager } from '@/auth/auth-manager';
import { tokenStore } from '@/auth/token-store';

type User = components['schemas']['User'];
type Profile = components['schemas']['Profile'];
export type RegisterInput = components['schemas']['RegisterRequest'];

export type SessionStatus =
  /** Reading the stored session at launch (the splash screen stays visible) */
  | 'restoring'
  | 'signedOut'
  /** Signed in without a biometric profile: the profile wizard is shown (M-06) */
  | 'needsProfile'
  | 'signedIn'
  /** A stored session exists but the server could not be reached */
  | 'unreachable';

type Session = {
  status: SessionStatus;
  /** Null until loaded, or when the backend does not offer GET /users/me yet */
  user: User | null;
  /** The biometric profile; null while the status is 'needsProfile' */
  profile: Profile | null;
  /** Message for the 'unreachable' state */
  problem: string | null;
  /** Both throw ApiError, so forms can show field errors */
  signIn: (email: string, password: string) => Promise<void>;
  register: (input: RegisterInput) => Promise<void>;
  signOut: () => Promise<void>;
  retry: () => void;
  /** Called after PUT /users/me/profile succeeded: the wizard then opens Home, editing stays */
  completeProfile: (profile: Profile) => void;
  /** Called after PATCH /users/me succeeded */
  updateUser: (user: User) => void;
};

export const authManager = createAuthManager({
  store: tokenStore,
  send: (request) => fetch(request),
  requestRefresh: (refreshToken) =>
    unwrap(api.POST('/auth/refresh', { body: { refresh_token: refreshToken } })),
});

// Every API call from now on goes through the token layer
setTransport(authManager.authorizedFetch);

const SessionContext = createContext<Session | null>(null);

async function fetchUser(): Promise<User | null> {
  try {
    return await unwrap(api.GET('/users/me'));
  } catch (error) {
    // The real backend does not serve GET /users/me yet (pending in B-28); sign-in still works
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

/** The profile, or null when the user has none yet (404) */
async function fetchProfile(): Promise<Profile | null> {
  try {
    return await unwrap(api.GET('/users/me/profile'));
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

type SessionState = { status: SessionStatus; user: User | null; profile: Profile | null; problem: string | null };

const SIGNED_OUT: SessionState = { status: 'signedOut', user: null, profile: null, problem: null };

async function loadAccountState(): Promise<SessionState> {
  const [user, profile] = await Promise.all([fetchUser(), fetchProfile()]);
  return { status: profile ? 'signedIn' : 'needsProfile', user, profile, problem: null };
}

/** Checks the stored session at launch; never throws */
async function restoreSession(): Promise<SessionState> {
  try {
    if (!(await authManager.hasStoredSession())) {
      return SIGNED_OUT;
    }
    // The access token is not stored, so a launch always starts with a refresh
    if (!(await authManager.refresh())) {
      return SIGNED_OUT;
    }
    return await loadAccountState();
  } catch (error) {
    return { status: 'unreachable', user: null, profile: null, problem: userMessage(toApiError(error)) };
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ ...SIGNED_OUT, status: 'restoring' });

  const loadAccount = useCallback(async () => {
    setState(await loadAccountState());
  }, []);

  useEffect(() => {
    let active = true;
    restoreSession().then((restored) => {
      if (active) {
        setState(restored);
      }
    });
    // A refresh that fails with 401 later (expired or revoked session) opens the login screen
    const unsubscribe = authManager.onSignedOut(() => setState(SIGNED_OUT));
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const pair = await unwrap(api.POST('/auth/login', { body: { email, password } }));
      await authManager.saveTokens(pair);
      await loadAccount();
    },
    [loadAccount],
  );

  const register = useCallback(
    async (input: RegisterInput) => {
      const pair = await unwrap(api.POST('/auth/register', { body: input }));
      await authManager.saveTokens(pair);
      await loadAccount();
    },
    [loadAccount],
  );

  const signOut = useCallback(async () => {
    const refreshToken = await authManager.getRefreshToken();
    if (refreshToken) {
      // Revokes the session on the server; signing out locally must work even offline
      await unwrap(api.POST('/auth/logout', { body: { refresh_token: refreshToken } })).catch(() => undefined);
    }
    await authManager.clear();
    setState(SIGNED_OUT);
  }, []);

  const retry = useCallback(() => {
    setState({ ...SIGNED_OUT, status: 'restoring' });
    restoreSession().then(setState);
  }, []);

  const completeProfile = useCallback((profile: Profile) => {
    setState((current) => ({ ...current, status: 'signedIn', profile }));
  }, []);

  const updateUser = useCallback((user: User) => {
    setState((current) => ({ ...current, user }));
  }, []);

  const value: Session = { ...state, signIn, register, signOut, retry, completeProfile, updateUser };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) {
    throw new Error('useSession must be used inside SessionProvider');
  }
  return session;
}
