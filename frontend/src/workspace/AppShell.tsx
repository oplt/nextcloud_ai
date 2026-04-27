import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import ButtonBase from '@mui/material/ButtonBase';
import IconButton from '@mui/material/IconButton';
import ChevronLeftOutlinedIcon from '@mui/icons-material/ChevronLeftOutlined';
import ChevronRightOutlinedIcon from '@mui/icons-material/ChevronRightOutlined';
import DarkModeOutlinedIcon from '@mui/icons-material/DarkModeOutlined';
import LightModeOutlinedIcon from '@mui/icons-material/LightModeOutlined';
import LogoutOutlinedIcon from '@mui/icons-material/LogoutOutlined';
import MenuOutlinedIcon from '@mui/icons-material/MenuOutlined';
import RefreshOutlinedIcon from '@mui/icons-material/RefreshOutlined';

import { AppButton } from '../components/ui/AppButton';
import { navItemForPath } from './navConfig';
import { useWorkspace } from './WorkspaceContext';

const SIDEBAR_COLLAPSED_KEY = 'workspace.sidebarCollapsed';

export function AppShell({
  themeMode,
  onToggleTheme,
}: {
  themeMode: 'dark' | 'light';
  onToggleTheme: () => void;
}) {
  const location = useLocation();
  const {
    user,
    navigation,
    busy,
    sessionRefreshing,
    workspaceRefreshing,
    backendStatus,
    userInitials,
    refreshWorkspace,
    logout,
  } = useWorkspace();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1';
    } catch {
      return false;
    }
  });
  const current = navItemForPath(location.pathname, navigation);
  const shellBusy = busy || sessionRefreshing || workspaceRefreshing;
  const backendLabel =
    backendStatus.kind === 'ready'
      ? 'Connected'
      : backendStatus.kind === 'degraded'
        ? 'Degraded'
        : backendStatus.kind === 'offline'
          ? 'Offline'
          : 'Checking';
  const backendClass =
    backendStatus.kind === 'ready'
      ? ' status-pill--connected'
      : backendStatus.kind === 'degraded'
        ? ' status-pill--degraded'
        : backendStatus.kind === 'offline'
          ? ' status-pill--offline'
          : ' status-pill--checking';

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMobileNavOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, sidebarCollapsed ? '1' : '0');
    } catch {
      /* ignore */
    }
  }, [sidebarCollapsed]);

  const shellClass = [
    'app-shell',
    mobileNavOpen ? 'app-shell--nav-open' : '',
    sidebarCollapsed ? 'app-shell--sidebar-collapsed' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={shellClass}>
      <ButtonBase
        type="button"
        className="mobile-nav-toggle"
        aria-label={mobileNavOpen ? 'Close navigation menu' : 'Open navigation menu'}
        aria-expanded={mobileNavOpen}
        aria-controls="workspace-sidebar"
        onClick={() => setMobileNavOpen((open) => !open)}
        sx={{
          display: { xs: 'inline-grid', md: 'none' },
        }}
      >
        <MenuOutlinedIcon fontSize="small" />
      </ButtonBase>
      {mobileNavOpen ? (
        <ButtonBase
          type="button"
          className="mobile-nav-scrim"
          aria-label="Close navigation"
          onClick={() => setMobileNavOpen(false)}
          sx={{
            display: { xs: 'block', md: 'none' },
          }}
        />
      ) : null}

      <aside id="workspace-sidebar" className="sidebar" aria-label="Workspace">
        <div className="sidebar__brand">
          <div className="sidebar__logo">DM</div>
          <div className="sidebar__brand-text">
            <strong>DocuMind</strong>
            <p>Knowledge cockpit</p>
          </div>
        </div>

        <nav className="sidebar__nav" aria-label="Primary navigation">
          {navigation.map((item, index) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === '/'}
              title={item.label}
              aria-label={sidebarCollapsed ? item.label : undefined}
              className={({ isActive }) =>
                `sidebar__nav-item${isActive ? ' sidebar__nav-item--active' : ''}`
              }
              style={{ animationDelay: `${index * 40}ms` }}
            >
              <span className="sidebar__nav-item-icon">{item.icon}</span>
              <span className="sidebar__nav-item-text">
                <strong>{item.label}</strong>
                <small>{item.heading}</small>
              </span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar__footer">
          <div className="sidebar__user">
            <span className="sidebar__avatar" title={user.full_name ?? user.username}>
              {userInitials}
            </span>
            <div className="sidebar__user-info">
              <strong>{user.full_name ?? user.username}</strong>
              <p>{user.email ?? 'No email synced'}</p>
            </div>
          </div>
          <div className="sidebar__actions">
            <AppButton type="button" variant="text" onClick={() => void refreshWorkspace()} title="Refresh workspace">
              <RefreshOutlinedIcon className="sidebar__action-icon" fontSize="small" aria-hidden="true" />
              <span className="sidebar__action-label">Refresh</span>
            </AppButton>
            <AppButton type="button" variant="text" onClick={() => void logout()} title="Sign out">
              <LogoutOutlinedIcon className="sidebar__action-icon" fontSize="small" aria-hidden="true" />
              <span className="sidebar__action-label">Sign out</span>
            </AppButton>
          </div>
        </div>
      </aside>

      <main className="app-main">
        <header className="app-header">
          <div className="app-header__left">
            <IconButton
              type="button"
              className="sidebar-rail-toggle"
              onClick={() => setSidebarCollapsed((c) => !c)}
              aria-expanded={!sidebarCollapsed}
              aria-controls="workspace-sidebar"
              title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              <span className="visually-hidden">
                {sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              </span>
              {sidebarCollapsed ? (
                <ChevronRightOutlinedIcon className="sidebar-rail-toggle__chev" fontSize="small" aria-hidden="true" />
              ) : (
                <ChevronLeftOutlinedIcon className="sidebar-rail-toggle__chev" fontSize="small" aria-hidden="true" />
              )}
            </IconButton>
            <div className="app-header__titles">
              <h1>{current.heading}</h1>
              <p>{current.description}</p>
            </div>
          </div>
          <div className="app-header__status">
            <AppButton
              type="button"
              variant="outlined"
              className="theme-toggle"
              onClick={onToggleTheme}
              aria-label={themeMode === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              title={themeMode === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            >
              {themeMode === 'dark' ? (
                <LightModeOutlinedIcon className="theme-toggle__icon" fontSize="small" aria-hidden="true" />
              ) : (
                <DarkModeOutlinedIcon className="theme-toggle__icon" fontSize="small" aria-hidden="true" />
              )}
              <span className="theme-toggle__label">
                {themeMode === 'dark' ? 'Light' : 'Dark'}
              </span>
            </AppButton>
            <span
              className={`status-pill${shellBusy ? ' status-pill--busy' : backendClass}`}
              title={shellBusy ? 'Workspace activity in progress' : backendStatus.detail ?? `Server ${backendLabel.toLowerCase()}`}
            >
              {shellBusy ? (busy ? 'Working…' : 'Refreshing…') : backendLabel}
            </span>
          </div>
        </header>

        <div className="app-content">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
