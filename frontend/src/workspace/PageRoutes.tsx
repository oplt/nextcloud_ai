import { lazy, Suspense } from 'react';
import { Navigate } from 'react-router-dom';

import { useWorkspace } from './WorkspaceContext';

const OverviewPage = lazy(async () => import('../pages/OverviewPage').then((m) => ({ default: m.OverviewPage })));
const ConnectorsPage = lazy(async () => import('../pages/ConnectorsPage').then((m) => ({ default: m.ConnectorsPage })));
const DocumentsPage = lazy(async () => import('../pages/DocumentsPage').then((m) => ({ default: m.DocumentsPage })));
const IntelligencePage = lazy(async () => import('../pages/IntelligencePage').then((m) => ({ default: m.IntelligencePage })));
const JobsPage = lazy(async () => import('../pages/JobsPage').then((m) => ({ default: m.JobsPage })));
const AdminPage = lazy(async () => import('../pages/AdminPage').then((m) => ({ default: m.AdminPage })));

function RouteFallback() {
  return <div className="app-loading">Loading section…</div>;
}

export function OverviewRoute() {
  const w = useWorkspace();
  return (
    <Suspense fallback={<RouteFallback />}>
      <OverviewPage
        user={w.user}
        connectors={w.connectors}
        documents={w.documents}
        sessions={w.sessions}
        activeSession={w.activeSessionView}
        loading={w.busy}
        workspaceLoading={w.workspaceDataLoading}
        workspaceError={w.workspaceDataError}
        chatError={w.chatAskError}
        chatFilters={w.chatFilters}
        availableMimeTypes={w.availableMimeTypes}
        onSelectSession={w.handleSelectSession}
        onAsk={w.handleAsk}
        onNewChat={w.handleNewChat}
        onDeleteSessions={w.handleDeleteSessions}
        onChatFilterChange={(patch) => w.setChatFilters((current) => ({ ...current, ...patch }))}
        onResetChatFilters={w.resetChatFilters}
      />
    </Suspense>
  );
}

export function ConnectorsRoute() {
  const w = useWorkspace();
  return (
    <Suspense fallback={<RouteFallback />}>
      <ConnectorsPage
        connectors={w.connectors}
        listLoading={w.workspaceDataLoading}
        listError={w.workspaceDataError}
        onCreate={w.handleCreate}
        onUpdate={w.handleUpdateConnector}
        onDelete={w.handleDelete}
        onTest={w.handleTestConnector}
        onSync={w.handleSyncConnector}
        onToggleActive={w.handleToggleConnectorActive}
      />
    </Suspense>
  );
}

export function DocumentsRoute() {
  const w = useWorkspace();
  return (
    <Suspense fallback={<RouteFallback />}>
      <DocumentsPage
        documents={w.documents}
        connectors={w.connectors}
        selectedDocument={w.selectedDocument}
        selectedDocumentId={w.selectedDocumentId}
        viewLoading={w.documentsViewLoading}
        viewError={w.documentsViewError}
        onSelect={w.handleSelectDocument}
        onReindex={w.handleReindexDocument}
      />
    </Suspense>
  );
}

export function IntelligenceRoute() {
  const w = useWorkspace();
  return (
    <Suspense fallback={<RouteFallback />}>
      <IntelligencePage
        overview={w.intelligenceOverview}
        loading={w.intelligenceLoading}
        error={w.intelligenceError}
        selectedDocument={w.selectedDocument}
        onSelectDocument={w.handleSelectDocumentById}
      />
    </Suspense>
  );
}

export function JobsRoute() {
  const w = useWorkspace();
  return (
    <Suspense fallback={<RouteFallback />}>
      <JobsPage
        jobs={w.jobs}
        connectors={w.connectors}
        loading={w.jobsLoading}
        refreshing={w.jobsRefreshing}
        error={w.jobsError}
        lastUpdatedAt={w.jobsLastUpdatedAt}
        onRefresh={async () => {
          await w.loadJobs();
        }}
        onRetry={w.handleRetryJob}
      />
    </Suspense>
  );
}

export function AdminRoute() {
  const w = useWorkspace();
  if (!w.isAdmin) {
    return <Navigate to="/" replace />;
  }
  return (
    <Suspense fallback={<RouteFallback />}>
      <AdminPage
        users={w.users}
        roles={w.roles}
        connectors={w.connectors}
        auditLogs={w.auditLogs}
        loading={w.busy || w.adminDataLoading}
        dataError={w.adminDataError}
        currentUserId={w.user.id}
        onCreateUser={w.handleCreateUser}
        onDeleteUsers={w.handleDeleteUsers}
        onUpdateUser={w.handleUpdateUser}
        onAssignConnectorOwner={w.handleAssignConnectorOwner}
        onSearchAuditLogs={w.handleSearchAuditLogs}
        onRefresh={w.loadAdminData}
      />
    </Suspense>
  );
}
