import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import ExpandMoreOutlinedIcon from '@mui/icons-material/ExpandMoreOutlined';
import Typography from '@mui/material/Typography';

import { AppButton } from '../components/ui/AppButton';
import { AppCard } from '../components/ui/AppCard';
import { AppCheckbox } from '../components/ui/AppCheckbox';
import { AppSelectField } from '../components/ui/AppSelectField';
import { AppTextField } from '../components/ui/AppTextField';
import type {
  AuditLog,
  AuditLogFilters,
  Connector,
  CreateUserPayload,
  Role,
  User,
} from '../types/api';

type AdminPageProps = {
  users: User[];
  roles: Role[];
  connectors: Connector[];
  auditLogs: AuditLog[];
  loading: boolean;
  dataError?: string | null;
  onCreateUser: (payload: CreateUserPayload) => Promise<void>;
  onUpdateUser: (userId: string, patch: { role_id?: string | null; is_active?: boolean }) => Promise<void>;
  onAssignConnectorOwner: (connectorId: string, ownerUserId: string | null) => Promise<void>;
  onSearchAuditLogs: (filters: AuditLogFilters) => Promise<void>;
  onRefresh: () => Promise<void>;
};

const INITIAL_USER_FORM: CreateUserPayload = {
  username: '',
  email: '',
  full_name: '',
  password: '',
  role_id: '',
  is_superuser: false,
};

const INITIAL_AUDIT_FILTERS: AuditLogFilters = {
  user_id: '',
  action: '',
  resource_type: '',
  resource_id: '',
  query: '',
};
const AUDIT_PAGE_SIZE = 8;

function formatDate(value: string): string {
  return new Date(value).toLocaleString();
}

export function AdminPage({
  users,
  roles,
  connectors,
  auditLogs,
  loading,
  dataError = null,
  onCreateUser,
  onUpdateUser,
  onAssignConnectorOwner,
  onSearchAuditLogs,
  onRefresh,
}: AdminPageProps) {
  const [userForm, setUserForm] = useState<CreateUserPayload>(INITIAL_USER_FORM);
  const [auditFilters, setAuditFilters] = useState<AuditLogFilters>(INITIAL_AUDIT_FILTERS);
  const [auditPage, setAuditPage] = useState(1);
  const [auditSectionExpanded, setAuditSectionExpanded] = useState(false);

  const userOptions = useMemo(
    () =>
      users.map((user) => ({
        id: user.id,
        label: user.full_name || user.email || user.username,
      })),
    [users],
  );

  const auditPageCount = Math.max(1, Math.ceil(auditLogs.length / AUDIT_PAGE_SIZE));
  const paginatedAuditLogs = useMemo(() => {
    const start = (auditPage - 1) * AUDIT_PAGE_SIZE;
    return auditLogs.slice(start, start + AUDIT_PAGE_SIZE);
  }, [auditLogs, auditPage]);

  useEffect(() => {
    setAuditPage(1);
  }, [auditLogs]);

  return (
    <section className="admin-page">
      {dataError ? (
        <div className="page-alert page-alert--error" role="alert">
          {dataError}
        </div>
      ) : null}
      <section className="overview-grid" aria-label="Admin summary">
        <AppCard className="card stat-card">
          <span className="stat-card__label">Users</span>
          <strong className="stat-card__value">{users.length}</strong>
        </AppCard>
        <AppCard className="card stat-card">
          <span className="stat-card__label">Roles</span>
          <strong className="stat-card__value">{roles.length}</strong>
        </AppCard>
        <AppCard className="card stat-card">
          <span className="stat-card__label">Connectors</span>
          <strong className="stat-card__value">{connectors.length}</strong>
        </AppCard>
        <AppCard className="card stat-card">
          <span className="stat-card__label">Audit entries</span>
          <strong className="stat-card__value">{auditLogs.length}</strong>
        </AppCard>
      </section>

      <AppCard component="section" className="card table-card" aria-label="Operator review shortcuts">
        <header className="panel-header">
          <div>
            <h3>Operator review</h3>
            <p className="filter-card__meta">One-click navigation for triage without reading raw logs first.</p>
          </div>
        </header>
        <ul className="admin-review-links">
          <li>
            <Link to="/jobs?status=failed">Failed jobs</Link>
            <span className="filter-card__meta"> Retry sync or reindex from the job card.</span>
          </li>
          <li>
            <Link to="/jobs?status=active">Active jobs</Link>
            <span className="filter-card__meta"> Watch long-running sync or indexing work.</span>
          </li>
          <li>
            <Link to="/intelligence">Intelligence & suggestions</Link>
            <span className="filter-card__meta"> Review heuristic tasks and document spotlights.</span>
          </li>
          <li>
            <Link to="/documents">Documents</Link>
            <span className="filter-card__meta"> Open a document and trigger reindex when extraction failed.</span>
          </li>
        </ul>
      </AppCard>

      <section className="split-layout admin-layout">
        <AppCard component="section" className="card form-card">
          <header className="panel-header">
            <h3>Create local user</h3>
            <AppButton type="button" variant="outlined" onClick={() => setUserForm(INITIAL_USER_FORM)}>
              Clear
            </AppButton>
          </header>

          <div className="admin-form-grid">
            <AppTextField
              label="Username"
              value={userForm.username}
              onChange={(event) => setUserForm((current) => ({ ...current, username: event.target.value }))}
            />
            <AppTextField
              label="Email"
              type="email"
              value={userForm.email ?? ''}
              onChange={(event) => setUserForm((current) => ({ ...current, email: event.target.value }))}
            />
            <AppTextField
              label="Full name"
              value={userForm.full_name ?? ''}
              onChange={(event) => setUserForm((current) => ({ ...current, full_name: event.target.value }))}
            />
            <AppTextField
              label="Password"
              type="password"
              value={userForm.password}
              onChange={(event) => setUserForm((current) => ({ ...current, password: event.target.value }))}
            />
            <AppSelectField
              label="Role"
              value={userForm.role_id ?? ''}
              onChange={(event) => setUserForm((current) => ({ ...current, role_id: event.target.value }))}
              options={[
                { label: 'Default role', value: '' },
                ...roles.map((role) => ({ label: role.name, value: role.id })),
              ]}
            />
            <label className="checkbox-row">
              <AppCheckbox
                checked={Boolean(userForm.is_superuser)}
                onChange={(event) => setUserForm((current) => ({ ...current, is_superuser: event.target.checked }))}
              />
              <span>Grant superuser access</span>
            </label>
          </div>

          <AppButton
            type="button"
            onClick={() => void onCreateUser(userForm)}
            disabled={loading || !userForm.username || !userForm.password}
          >
            Create user
          </AppButton>
        </AppCard>

        <AppCard component="section" className="card table-card">
          <header className="panel-header">
            <h3>User management</h3>
            <AppButton type="button" variant="outlined" onClick={() => void onRefresh()} disabled={loading}>
              Refresh
            </AppButton>
          </header>

          <div className="admin-table">
            {users.map((user) => (
              <div key={`${user.id}:${user.updated_at}:${user.role?.id ?? 'none'}:${user.is_active}`} className="admin-row">
                <div>
                  <strong>{user.full_name || user.username}</strong>
                  <p>{user.email || user.username}</p>
                </div>
                <AppSelectField
                  label="Role"
                  defaultValue={user.role?.id ?? ''}
                  onChange={(event) =>
                    void onUpdateUser(user.id, { role_id: event.target.value || null })
                  }
                  options={[
                    { label: 'No role', value: '' },
                    ...roles.map((role) => ({ label: role.name, value: role.id })),
                  ]}
                />
                <label className="checkbox-row">
                  <AppCheckbox
                    defaultChecked={user.is_active}
                    onChange={(event) =>
                      void onUpdateUser(user.id, { is_active: event.target.checked })
                    }
                  />
                  <span>{user.is_active ? 'Active' : 'Disabled'}</span>
                </label>
              </div>
            ))}
          </div>
        </AppCard>
      </section>

      <AppCard component="section" className="card table-card">
        <header className="panel-header">
          <h3>Connector ownership</h3>
        </header>

        <div className="admin-table">
          {connectors.map((connector) => (
            <div key={`${connector.id}:${connector.owner_user_id ?? 'none'}`} className="admin-row">
              <div>
                <strong>{connector.display_name}</strong>
                <p>{connector.base_url}</p>
              </div>
              <AppSelectField
                label="Owner"
                defaultValue={connector.owner_user_id ?? ''}
                onChange={(event) =>
                  void onAssignConnectorOwner(connector.id, event.target.value || null)
                }
                options={[
                  { label: 'Unassigned', value: '' },
                  ...userOptions.map((option) => ({ label: option.label, value: option.id })),
                ]}
              />
            </div>
          ))}
        </div>
      </AppCard>

      <AppCard component="section" className="card table-card">
        <header className="panel-header">
          <div>
            <h3>Audit logs</h3>
            <p className="filter-card__meta">
              {auditLogs.length} entries loaded. Expand this section to review and search logs.
            </p>
          </div>
          <div className="audit-log-toolbar">
            <Typography component="span">Page {auditPage} / {auditPageCount}</Typography>
            <AppButton
              type="button"
              variant="text"
              className={`audit-log-section-toggle${auditSectionExpanded ? ' audit-log-section-toggle--expanded' : ''}`}
              onClick={() => setAuditSectionExpanded((current) => !current)}
              aria-expanded={auditSectionExpanded}
            >
              <ExpandMoreOutlinedIcon fontSize="small" aria-hidden="true" />
              <span>{auditSectionExpanded ? 'Collapse' : 'Expand'}</span>
            </AppButton>
            <AppButton type="button" variant="outlined" onClick={() => void onSearchAuditLogs(auditFilters)} disabled={loading}>
              Search
            </AppButton>
          </div>
        </header>

        {auditSectionExpanded ? (
          <>
            <div className="filter-grid">
              <AppSelectField
                label="User"
                value={auditFilters.user_id ?? ''}
                onChange={(event) => setAuditFilters((current) => ({ ...current, user_id: event.target.value }))}
                options={[
                  { label: 'All users', value: '' },
                  ...userOptions.map((option) => ({ label: option.label, value: option.id })),
                ]}
              />
              <AppTextField
                label="Action"
                value={auditFilters.action ?? ''}
                onChange={(event) => setAuditFilters((current) => ({ ...current, action: event.target.value }))}
                placeholder="connector.updated"
              />
              <AppTextField
                label="Resource type"
                value={auditFilters.resource_type ?? ''}
                onChange={(event) => setAuditFilters((current) => ({ ...current, resource_type: event.target.value }))}
                placeholder="connector"
              />
              <AppTextField
                label="Query"
                value={auditFilters.query ?? ''}
                onChange={(event) => setAuditFilters((current) => ({ ...current, query: event.target.value }))}
                placeholder="owner changed"
              />
            </div>

            <div className="audit-log-list">
              {paginatedAuditLogs.map((entry) => (
                <article key={entry.id} className="audit-log-card">
                  <div className="audit-log-card__top">
                    <div className="audit-log-card__headline">
                      <strong>{entry.action}</strong>
                      <Typography component="span">{formatDate(entry.created_at)}</Typography>
                    </div>
                  </div>
                  <p>{entry.message || 'No message recorded'}</p>
                  <div>
                    <strong>User</strong>
                    <p>{entry.user?.full_name || entry.user?.username || 'system'}</p>
                  </div>
                  <div>
                    <strong>Resource</strong>
                    <p>{entry.resource_type}{entry.resource_id ? `:${entry.resource_id}` : ''}</p>
                  </div>
                </article>
              ))}
            </div>

            <div className="audit-log-pagination">
              <AppButton
                type="button"
                variant="outlined"
                onClick={() => setAuditPage((current) => Math.max(1, current - 1))}
                disabled={auditPage === 1}
              >
                Previous
              </AppButton>
              <Typography component="span">
                Showing {(auditPage - 1) * AUDIT_PAGE_SIZE + (paginatedAuditLogs.length ? 1 : 0)}
                {' '}-{' '}
                {(auditPage - 1) * AUDIT_PAGE_SIZE + paginatedAuditLogs.length}
                {' '}of {auditLogs.length}
              </Typography>
              <AppButton
                type="button"
                variant="outlined"
                onClick={() => setAuditPage((current) => Math.min(auditPageCount, current + 1))}
                disabled={auditPage === auditPageCount}
              >
                Next
              </AppButton>
            </div>
          </>
        ) : null}
      </AppCard>
    </section>
  );
}
