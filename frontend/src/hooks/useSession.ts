import { useCallback, useEffect, useState } from 'react';

import {
  ensureCsrfToken,
  getCurrentUser,
  hasSessionCookie,
  login as apiLogin,
  logout as apiLogout,
} from '../api/client';
import type { User } from '../types/api';

type SessionState = {
  user: User | null;
  loading: boolean;
  error: string | null;
  sessionRefreshing: boolean;
};

function mapLoginError(error: unknown): string {
  if (!(error instanceof Error)) {
    return 'Sign in failed';
  }
  const msg = error.message;
  const lower = msg.toLowerCase();
  if (lower.includes('csrf') || msg.includes('403')) {
    return 'Security token missing or expired. Reload the page and try again.';
  }
  if (error.message === 'UNAUTHORIZED' || lower.includes('401') || lower.includes('invalid') || lower.includes('incorrect')) {
    return 'Invalid email or password.';
  }
  if (lower.includes('failed to fetch') || error.name === 'TypeError') {
    return 'Network error: could not reach the server.';
  }
  return msg || 'Sign in failed';
}

export function useSession() {
  const [state, setState] = useState<SessionState>({
    user: null,
    loading: true,
    error: null,
    sessionRefreshing: false,
  });

  const refresh = useCallback(async (options?: { silent?: boolean }) => {
    const silent = options?.silent ?? false;
    if (silent) {
      setState((current) => ({ ...current, sessionRefreshing: true, error: null }));
    } else {
      setState((current) => ({ ...current, loading: true, error: null }));
    }

    try {
      await ensureCsrfToken();
    } catch {
      // Best effort: the app can still render the login screen without a CSRF cookie.
    }

    if (!hasSessionCookie()) {
      setState({ user: null, loading: false, error: null, sessionRefreshing: false });
      return;
    }

    try {
      const user = await getCurrentUser();
      setState({ user, loading: false, error: null, sessionRefreshing: false });
    } catch (error) {
      if (error instanceof Error && error.message === 'UNAUTHORIZED') {
        setState({ user: null, loading: false, error: null, sessionRefreshing: false });
        return;
      }
      setState({
        user: null,
        loading: false,
        sessionRefreshing: false,
        error: error instanceof Error ? error.message : 'Unable to load session',
      });
    }
  }, []);

  useEffect(() => {
    const timerId = window.setTimeout(() => {
      void refresh();
    }, 0);
    return () => {
      window.clearTimeout(timerId);
    };
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    try {
      await ensureCsrfToken();
      const session = await apiLogin(email, password);
      setState({ user: session.user, loading: false, error: null, sessionRefreshing: false });
    } catch (error) {
      setState({
        user: null,
        loading: false,
        sessionRefreshing: false,
        error: mapLoginError(error),
      });
    }
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setState({ user: null, loading: false, error: null, sessionRefreshing: false });
  }, []);

  const clearError = useCallback(() => {
    setState((current) => ({ ...current, error: null }));
  }, []);

  return { ...state, refresh, login, logout, clearError };
}
