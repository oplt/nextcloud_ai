import { useEffect, useMemo, useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import CssBaseline from '@mui/material/CssBaseline';
import GlobalStyles from '@mui/material/GlobalStyles';
import { ThemeProvider, alpha } from '@mui/material/styles';

import { ToastProvider } from './components/ui/ToastProvider';
import { useSession } from './hooks/useSession';
import { LoginPage } from './pages/LoginPage';
import { buildAppTheme, type ThemeMode } from './theme';
import { AppShell } from './workspace/AppShell';
import {
  AdminRoute,
  ConnectorsRoute,
  DocumentsRoute,
  IntelligenceRoute,
  JobsRoute,
  OverviewRoute,
} from './workspace/PageRoutes';
import { WorkspaceProvider } from './workspace/WorkspaceContext';

const THEME_STORAGE_KEY = 'workspace.themeMode';

function AuthenticatedApp({
  themeMode,
  onToggleTheme,
}: {
  themeMode: ThemeMode;
  onToggleTheme: () => void;
}) {
  const { user, loading, error, login, logout, refresh, sessionRefreshing, clearError } = useSession();

  if (loading) {
    return <div className="app-loading">Loading workspace</div>;
  }
  if (!user) {
    return <LoginPage onLogin={login} error={error} onDismissError={clearError} />;
  }

  return (
    <WorkspaceProvider
      user={user}
      sessionRefreshing={sessionRefreshing}
      refresh={refresh}
      sessionLogout={logout}
    >
      <Routes>
        <Route element={<AppShell themeMode={themeMode} onToggleTheme={onToggleTheme} />}>
          <Route index element={<OverviewRoute />} />
          <Route path="connectors" element={<ConnectorsRoute />} />
          <Route path="documents" element={<DocumentsRoute />} />
          <Route path="intelligence" element={<IntelligenceRoute />} />
          <Route path="jobs" element={<JobsRoute />} />
          <Route path="admin" element={<AdminRoute />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </WorkspaceProvider>
  );
}

export default function App() {
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => {
    try {
      const stored = localStorage.getItem(THEME_STORAGE_KEY);
      return stored === 'dark' ? 'dark' : 'light';
    } catch {
      return 'light';
    }
  });
  const theme = useMemo(() => buildAppTheme(themeMode), [themeMode]);

  useEffect(() => {
    document.documentElement.dataset.theme = themeMode;
    document.documentElement.style.colorScheme = themeMode;
    try {
      localStorage.setItem(THEME_STORAGE_KEY, themeMode);
    } catch {
      /* ignore */
    }
  }, [themeMode]);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <GlobalStyles
        styles={{
          ':root': {
            '--bg': theme.palette.background.default,
            '--bg-elevated': theme.palette.mode === 'dark' ? '#141414' : '#F7F7F7',
            '--bg-panel': alpha(theme.palette.background.paper, theme.palette.mode === 'dark' ? 0.84 : 0.96),
            '--bg-panel-strong': theme.palette.background.paper,
            '--bg-soft': alpha(theme.palette.text.primary, 0.04),
            '--bg-muted': alpha(theme.palette.text.primary, 0.07),
            '--line': theme.palette.divider,
            '--line-strong': alpha(theme.palette.text.secondary, theme.palette.mode === 'dark' ? 0.24 : 0.34),
            '--line-focus': theme.palette.primary.main,
            '--text': theme.palette.text.primary,
            '--text-soft': theme.palette.text.secondary,
            '--text-muted': theme.palette.mode === 'dark' ? '#9D9D9D' : '#616161',
            '--accent': theme.palette.primary.main,
            '--accent-strong': theme.palette.primary.dark,
            '--accent-soft': alpha(theme.palette.primary.main, 0.16),
            '--accent-glow': alpha(theme.palette.primary.main, 0.22),
            '--accent-warm': theme.palette.secondary.main,
            '--accent-warm-soft': alpha(theme.palette.secondary.main, 0.18),
            '--danger': theme.palette.error.main,
            '--danger-soft': alpha(theme.palette.error.main, 0.18),
            '--warning': theme.palette.warning.main,
            '--warning-soft': alpha(theme.palette.warning.main, 0.16),
            '--success': theme.palette.success.main,
            '--success-soft': alpha(theme.palette.success.main, 0.16),
            '--shadow-sm':
              theme.palette.mode === 'dark'
                ? '0 10px 22px rgba(0, 0, 0, 0.22)'
                : '0 10px 22px rgba(62, 62, 62, 0.08)',
            '--shadow-md':
              theme.palette.mode === 'dark'
                ? '0 22px 50px rgba(0, 0, 0, 0.3)'
                : '0 22px 50px rgba(62, 62, 62, 0.12)',
            '--shadow-lg':
              theme.palette.mode === 'dark'
                ? '0 34px 80px rgba(0, 0, 0, 0.38)'
                : '0 34px 80px rgba(62, 62, 62, 0.14)',
          },
          body: {
            background:
              theme.palette.mode === 'dark'
                ? `radial-gradient(circle at 16% 10%, ${alpha('#00FFAB', 0.18)}, transparent 18rem),
                   radial-gradient(circle at 84% 16%, ${alpha('#6DFFC9', 0.14)}, transparent 16rem),
                   linear-gradient(180deg, #171717 0%, #101010 30%, #0A0A0A 100%)`
                : `radial-gradient(circle at 16% 8%, ${alpha('#00FFAB', 0.12)}, transparent 16rem),
                   radial-gradient(circle at 84% 12%, ${alpha('#6DFFC9', 0.08)}, transparent 14rem),
                   linear-gradient(180deg, #FFFFFF 0%, #FCFFFE 42%, #F4FFF9 100%)`,
          },
          'body::before': {
            backgroundImage:
              theme.palette.mode === 'dark'
                ? `linear-gradient(${alpha('#FFFFFF', 0.02)} 1px, transparent 1px),
                   linear-gradient(90deg, ${alpha('#FFFFFF', 0.02)} 1px, transparent 1px)`
                : `linear-gradient(${alpha('#0A0A0A', 0.04)} 1px, transparent 1px),
                   linear-gradient(90deg, ${alpha('#0A0A0A', 0.04)} 1px, transparent 1px)`,
          },
        }}
      />
      <BrowserRouter>
        <ToastProvider>
          <AuthenticatedApp
            themeMode={themeMode}
            onToggleTheme={() =>
              setThemeMode((current) => (current === 'dark' ? 'light' : 'dark'))
            }
          />
        </ToastProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}
