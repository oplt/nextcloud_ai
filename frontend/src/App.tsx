import { useEffect, useMemo, useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import CssBaseline from '@mui/material/CssBaseline';
import GlobalStyles from '@mui/material/GlobalStyles';
import { ThemeProvider, alpha } from '@mui/material/styles';

import { ToastProvider } from './components/ui/ToastProvider';
import { useSession } from './hooks/useSession';
import { LoginPage } from './pages/LoginPage';
import { brandPalette, buildAppTheme, type ThemeMode } from './theme';
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
            '--bg-elevated': theme.palette.mode === 'dark' ? '#1f1c38' : brandPalette.secondary,
            '--bg-panel': alpha(theme.palette.background.paper, theme.palette.mode === 'dark' ? 0.84 : 0.96),
            '--bg-panel-strong': theme.palette.background.paper,
            '--bg-soft': alpha(brandPalette.headline, 0.04),
            '--bg-muted': alpha(brandPalette.headline, 0.07),
            '--bg-secondary': brandPalette.secondary,
            '--bg-tertiary': brandPalette.tertiary,
            '--line': theme.palette.divider,
            '--line-strong': alpha(brandPalette.headline, theme.palette.mode === 'dark' ? 0.24 : 0.34),
            '--line-focus': brandPalette.highlight,
            '--text': theme.palette.text.primary,
            '--text-soft': theme.palette.text.secondary,
            '--text-muted': theme.palette.mode === 'dark' ? alpha(brandPalette.bg, 0.7) : alpha(brandPalette.paragraph, 0.7),
            '--headline': brandPalette.headline,
            '--paragraph': brandPalette.paragraph,
            '--stroke': brandPalette.stroke,
            '--accent': brandPalette.highlight,
            '--accent-strong': '#e6c200',
            '--accent-soft': alpha(brandPalette.highlight, 0.16),
            '--accent-glow': alpha(brandPalette.highlight, 0.22),
            '--accent-warm': brandPalette.headline,
            '--accent-warm-soft': alpha(brandPalette.headline, 0.12),
            '--button-bg': brandPalette.button,
            '--button-text': brandPalette.buttonText,
            '--danger': theme.palette.error.main,
            '--danger-soft': alpha(theme.palette.error.main, 0.18),
            '--warning': brandPalette.highlight,
            '--warning-soft': alpha(brandPalette.highlight, 0.16),
            '--success': brandPalette.tertiary,
            '--success-soft': alpha(brandPalette.tertiary, 0.32),
            '--shadow-sm':
              theme.palette.mode === 'dark'
                ? '0 10px 22px rgba(0, 0, 0, 0.32)'
                : '0 10px 22px rgba(39, 35, 67, 0.08)',
            '--shadow-md':
              theme.palette.mode === 'dark'
                ? '0 22px 50px rgba(0, 0, 0, 0.38)'
                : '0 22px 50px rgba(39, 35, 67, 0.12)',
            '--shadow-lg':
              theme.palette.mode === 'dark'
                ? '0 34px 80px rgba(0, 0, 0, 0.42)'
                : '0 34px 80px rgba(39, 35, 67, 0.14)',
          },
          body: {
            background:
              theme.palette.mode === 'dark'
                ? `radial-gradient(circle at 16% 10%, ${alpha(brandPalette.highlight, 0.18)}, transparent 18rem),
                   radial-gradient(circle at 84% 16%, ${alpha(brandPalette.tertiary, 0.14)}, transparent 16rem),
                   linear-gradient(180deg, #1f1c38 0%, #1a1730 30%, ${brandPalette.headline} 100%)`
                : `radial-gradient(circle at 16% 8%, ${alpha(brandPalette.highlight, 0.12)}, transparent 16rem),
                   radial-gradient(circle at 84% 12%, ${alpha(brandPalette.tertiary, 0.18)}, transparent 14rem),
                   linear-gradient(180deg, ${brandPalette.bg} 0%, ${brandPalette.bg} 42%, ${brandPalette.secondary} 100%)`,
          },
          'body::before': {
            backgroundImage:
              theme.palette.mode === 'dark'
                ? `linear-gradient(${alpha(brandPalette.bg, 0.03)} 1px, transparent 1px),
                   linear-gradient(90deg, ${alpha(brandPalette.bg, 0.03)} 1px, transparent 1px)`
                : `linear-gradient(${alpha(brandPalette.headline, 0.04)} 1px, transparent 1px),
                   linear-gradient(90deg, ${alpha(brandPalette.headline, 0.04)} 1px, transparent 1px)`,
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
