import type { ReactNode } from 'react';
import HomeOutlinedIcon from '@mui/icons-material/HomeOutlined';
import HubOutlinedIcon from '@mui/icons-material/HubOutlined';
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined';
import InsightsOutlinedIcon from '@mui/icons-material/InsightsOutlined';
import ScheduleOutlinedIcon from '@mui/icons-material/ScheduleOutlined';
import AdminPanelSettingsOutlinedIcon from '@mui/icons-material/AdminPanelSettingsOutlined';

export type WorkspaceNavItem = {
  path: string;
  label: string;
  heading: string;
  description: string;
  icon: ReactNode;
};

export type WorkspaceSection = 'overview' | 'connectors' | 'documents' | 'intelligence' | 'jobs' | 'admin';

export function workspaceSectionFromPath(pathname: string): WorkspaceSection {
  const p = pathname.replace(/\/$/, '') || '/';
  if (p.startsWith('/connectors')) return 'connectors';
  if (p.startsWith('/documents')) return 'documents';
  if (p.startsWith('/intelligence')) return 'intelligence';
  if (p.startsWith('/jobs')) return 'jobs';
  if (p.startsWith('/admin')) return 'admin';
  return 'overview';
}

export const WORKSPACE_PATHS = {
  overview: '/',
  connectors: '/connectors',
  documents: '/documents',
  intelligence: '/intelligence',
  jobs: '/jobs',
  admin: '/admin',
} as const;

export function buildWorkspaceNav(includeAdmin: boolean): WorkspaceNavItem[] {
  const items: WorkspaceNavItem[] = [
    {
      path: WORKSPACE_PATHS.overview,
      label: 'Home',
      heading: 'Private company knowledge workspace',
      description: 'Track connector health, browse synced content, and work with the latest chat context.',
      icon: <HomeOutlinedIcon fontSize="small" />,
    },
    {
      path: WORKSPACE_PATHS.connectors,
      label: 'Connectors',
      heading: 'Connector management',
      description: 'Configure Nextcloud sources, validate credentials, and run sync jobs from one place.',
      icon: <HubOutlinedIcon fontSize="small" />,
    },
    {
      path: WORKSPACE_PATHS.documents,
      label: 'Documents',
      heading: 'Document catalog',
      description: 'Review indexed files, inspect metadata, and requeue document parsing when needed.',
      icon: <DescriptionOutlinedIcon fontSize="small" />,
    },
    {
      path: WORKSPACE_PATHS.intelligence,
      label: 'Intelligence',
      heading: 'Structured workflow cockpit',
      description: 'Track meetings, contracts, compliance gaps, and graph-linked work from synced content.',
      icon: <InsightsOutlinedIcon fontSize="small" />,
    },
    {
      path: WORKSPACE_PATHS.jobs,
      label: 'Jobs',
      heading: 'Operational job monitor',
      description: 'Track sync and reindex execution, watch failures, and follow retry activity in real time.',
      icon: <ScheduleOutlinedIcon fontSize="small" />,
    },
  ];

  if (includeAdmin) {
    items.push({
      path: WORKSPACE_PATHS.admin,
      label: 'Admin',
      heading: 'Pilot operations console',
      description: 'Manage users, roles, ownership, and audit activity for the SME deployment.',
      icon: <AdminPanelSettingsOutlinedIcon fontSize="small" />,
    });
  }

  return items;
}

export function navItemForPath(pathname: string, items: WorkspaceNavItem[]): WorkspaceNavItem {
  const p = pathname.replace(/\/$/, '') || '/';
  const nonRoot = items.filter((item) => item.path !== '/');
  const match = nonRoot.find((item) => p === item.path || p.startsWith(`${item.path}/`));
  if (match) {
    return match;
  }
  return items.find((item) => item.path === '/') ?? items[0];
}
