import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import DeleteIcon from '@mui/icons-material/Delete';
import ExpandMoreOutlinedIcon from '@mui/icons-material/ExpandMoreOutlined';
import VisibilityOffOutlinedIcon from '@mui/icons-material/VisibilityOffOutlined';
import VisibilityOutlinedIcon from '@mui/icons-material/VisibilityOutlined';
import Alert from '@mui/material/Alert';
import IconButton from '@mui/material/IconButton';
import InputAdornment from '@mui/material/InputAdornment';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';

import { AppButton } from '../components/ui/AppButton';
import { AppCard } from '../components/ui/AppCard';
import { AppCheckbox } from '../components/ui/AppCheckbox';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
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
    currentUserId: string;
    onCreateUser: (payload: CreateUserPayload) => Promise<void>;
    onDeleteUsers: (userIds: string[]) => Promise<void>;
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
                              currentUserId,
                              onCreateUser,
                              onDeleteUsers,
                              onUpdateUser,
                              onAssignConnectorOwner,
                              onSearchAuditLogs,
                              onRefresh,
                          }: AdminPageProps) {
    const [userForm, setUserForm] = useState<CreateUserPayload>(INITIAL_USER_FORM);
    const [auditFilters, setAuditFilters] = useState<AuditLogFilters>(INITIAL_AUDIT_FILTERS);
    const [auditPage, setAuditPage] = useState(1);
    const [connectorSectionExpanded, setConnectorSectionExpanded] = useState(false);
    const [auditSectionExpanded, setAuditSectionExpanded] = useState(false);
    const [showPassword, setShowPassword] = useState(false);
    const [userPendingDelete, setUserPendingDelete] = useState<User | null>(null);

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
    const canCreateUser = userForm.username.trim().length > 0 && userForm.password.trim().length > 0;
    const passwordTooShort = userForm.password.length > 0 && userForm.password.length < 10;
    const createUserPayload: CreateUserPayload = {
        ...userForm,
        username: userForm.username.trim(),
        email: userForm.email?.trim() || null,
        full_name: userForm.full_name?.trim() || null,
        role_id: userForm.role_id || null,
    };

    useEffect(() => {
        setAuditPage(1);
    }, [auditLogs]);

    const confirmDeleteUser = async () => {
        if (!userPendingDelete || userPendingDelete.id === currentUserId) {
            return;
        }
        await onDeleteUsers([userPendingDelete.id]);
        setUserPendingDelete(null);
    };

    return (
        <section className="admin-page">
            {dataError ? (
                <Alert severity="error" className="page-alert">
                    {dataError}
                </Alert>
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

            <section
                className="admin-equal-row admin-equal-row--three"
                style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
                    gridAutoRows: '1fr',
                    alignItems: 'stretch',
                    gap: '1rem',
                }}
            >
                <AppCard
                    component="section"
                    className="card table-card"
                    aria-label="Operator review shortcuts"
                    style={{ height: '25rem', minWidth: 0, display: 'flex', flexDirection: 'column' }}
                >
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

                <AppCard
                    component="section"
                    className="card form-card"
                    style={{ height: '25rem', minWidth: 0, display: 'flex', flexDirection: 'column' }}
                >
                    <header className="panel-header">
                        <h3>Add local user</h3>
                        <AppButton type="button" variant="outlined" onClick={() => setUserForm(INITIAL_USER_FORM)}>
                            Clear
                        </AppButton>
                    </header>

                    <div className="admin-form-grid" style={{ flex: 1, minHeight: 0 }}>
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
                            type={showPassword ? 'text' : 'password'}
                            value={userForm.password}
                            onChange={(event) => setUserForm((current) => ({ ...current, password: event.target.value }))}
                            error={passwordTooShort}
                            helperText={passwordTooShort ? 'Password must be at least 10 characters.' : 'Minimum 10 characters'}
                            InputProps={{
                                endAdornment: (
                                    <InputAdornment position="end">
                                        <IconButton
                                            type="button"
                                            aria-label={showPassword ? 'Hide password' : 'Show password'}
                                            title={showPassword ? 'Hide password' : 'Show password'}
                                            edge="end"
                                            onClick={() => setShowPassword((visible) => !visible)}
                                        >
                                            {showPassword ? <VisibilityOffOutlinedIcon fontSize="small" /> : <VisibilityOutlinedIcon fontSize="small" />}
                                        </IconButton>
                                    </InputAdornment>
                                ),
                            }}
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
                        onClick={() => void onCreateUser(createUserPayload)}
                        disabled={loading || !canCreateUser}
                    >
                        Add user
                    </AppButton>
                </AppCard>

                <AppCard
                    component="section"
                    className="card table-card"
                    style={{ height: '25rem', minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
                >
                    <header className="panel-header" style={{ alignItems: 'flex-start', gap: '0.75rem' }}>
                        <div>
                            <h3>User management</h3>
                            <p className="filter-card__meta">Manage roles, status, and user deletion.</p>
                        </div>
                        <AppButton type="button" variant="outlined" onClick={() => void onRefresh()} disabled={loading}>
                            Refresh
                        </AppButton>
                    </header>

                    <div
                        className="admin-table"
                        style={{
                            flex: 1,
                            minHeight: 0,
                            overflowY: 'auto',
                            overflowX: 'hidden',
                            paddingRight: '0.5rem',
                            scrollbarGutter: 'stable',
                        }}
                    >
                        {users.map((user) => {
                            const displayName = user.full_name || user.username;
                            const isCurrentUser = user.id === currentUserId;

                            return (
                                <div
                                    key={`${user.id}:${user.updated_at}:${user.role?.id ?? 'none'}:${user.is_active}`}
                                    className="admin-row"
                                    style={{
                                        gridTemplateColumns: 'minmax(0, 1.4fr) minmax(8rem, 0.9fr) auto minmax(6rem, auto)',
                                        alignItems: 'center',
                                        gap: '0.75rem',
                                        padding: '0.9rem',
                                    }}
                                >
                                    <div style={{ minWidth: 0 }}>
                                        <strong style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {displayName}
                                        </strong>
                                        <p style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {user.email || user.username}{isCurrentUser ? ' · You' : ''}
                                        </p>
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

                                    <Tooltip title={isCurrentUser ? 'Current user cannot be deleted' : `Delete ${displayName}`}>
                                        <span style={{ display: 'inline-flex', justifyContent: 'center' }}>
                                            <IconButton
                                                type="button"
                                                disabled={loading || isCurrentUser}
                                                onClick={() => setUserPendingDelete(user)}
                                                aria-label={isCurrentUser ? 'Current user cannot be deleted' : `Delete ${displayName}`}
                                                size="small"
                                                sx={{
                                                    color: 'var(--danger)',
                                                    border: '1px solid rgba(217, 72, 69, 0.2)',
                                                    backgroundColor: 'rgba(217, 72, 69, 0.06)',
                                                    '&:hover': {
                                                        backgroundColor: 'rgba(217, 72, 69, 0.12)',
                                                        borderColor: 'rgba(217, 72, 69, 0.35)',
                                                    },
                                                    '&.Mui-disabled': {
                                                        color: 'rgba(45, 51, 74, 0.28)',
                                                        borderColor: 'rgba(45, 51, 74, 0.1)',
                                                        backgroundColor: 'rgba(45, 51, 74, 0.03)',
                                                    },
                                                }}
                                            >
                                                <DeleteIcon fontSize="small" />
                                            </IconButton>
                                        </span>
                                    </Tooltip>

                                    <label className="checkbox-row" style={{ justifyContent: 'flex-end', whiteSpace: 'nowrap' }}>
                                        <AppCheckbox
                                            defaultChecked={user.is_active}
                                            onChange={(event) =>
                                                void onUpdateUser(user.id, { is_active: event.target.checked })
                                            }
                                        />
                                        <span>{user.is_active ? 'Active' : 'Disabled'}</span>
                                    </label>
                                </div>
                            );
                        })}
                    </div>
                </AppCard>
            </section>

            <section
                className="admin-equal-row admin-equal-row--two"
                style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
                    alignItems: 'start',
                    gap: '1rem',
                    marginTop: '1rem',
                }}
            >
                <AppCard component="section" className="card table-card" style={{ minWidth: 0 }}>
                    <header className="panel-header">
                        <div>
                            <h3>Connector ownership</h3>
                            <p className="filter-card__meta">Expand this section to assign connector owners.</p>
                        </div>
                        <AppButton
                            type="button"
                            variant="text"
                            className={`audit-log-section-toggle${connectorSectionExpanded ? ' audit-log-section-toggle--expanded' : ''}`}
                            onClick={() => setConnectorSectionExpanded((current) => !current)}
                            aria-expanded={connectorSectionExpanded}
                        >
                            <ExpandMoreOutlinedIcon fontSize="small" aria-hidden="true" />
                            <span>{connectorSectionExpanded ? 'Collapse' : 'Expand'}</span>
                        </AppButton>
                    </header>

                    {connectorSectionExpanded ? (
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
                    ) : null}
                </AppCard>

                <AppCard component="section" className="card table-card" style={{ minWidth: 0 }}>
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
            <ConfirmDialog
                open={Boolean(userPendingDelete)}
                title="Delete user?"
                description={
                    userPendingDelete ? (
                        <Typography component="p">
                            This permanently removes <strong>{userPendingDelete.full_name || userPendingDelete.username}</strong>. Their chat history is deleted, while connector ownership, audit logs, jobs, and documents keep their records with the user reference cleared.
                        </Typography>
                    ) : null
                }
                confirmLabel="Delete user"
                cancelLabel="Cancel"
                variant="danger"
                onCancel={() => setUserPendingDelete(null)}
                onConfirm={() => void confirmDeleteUser()}
            />
        </section>
    );
}