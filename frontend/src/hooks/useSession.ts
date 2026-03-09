import { useCallback, useEffect, useState } from 'react';

import {
  ensureCsrfToken,
  getCurrentUser,
  login as apiLogin,
  logout as apiLogout,
} from '../api/client';
import type { User } from '../types/api';

type SessionState = {
  user: User | null;
  loading: boolean;
  error: string | null;
};

export function useSession() {
  const [state, setState] = useState<SessionState>({ user: null, loading: true, error: null });

  const refresh = useCallback(async () => {
    setState((current) => ({ ...current, loading: true, error: null }));

    try {
      await ensureCsrfToken();
    } catch {
      // Best effort: the app can still render the login screen without a CSRF cookie.
    }

    try {
      const user = await getCurrentUser();
      setState({ user, loading: false, error: null });
    } catch (error) {
      if (error instanceof Error && error.message === 'UNAUTHORIZED') {
        setState({ user: null, loading: false, error: null });
        return;
      }
      setState({
        user: null,
        loading: false,
        error: error instanceof Error ? error.message : 'Unable to load session',
      });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    await ensureCsrfToken();
    const session = await apiLogin(email, password);
    setState({ user: session.user, loading: false, error: null });
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setState({ user: null, loading: false, error: null });
  }, []);

  return { ...state, refresh, login, logout };
}
